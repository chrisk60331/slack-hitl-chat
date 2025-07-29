# CloudWatch Log Group for Step Functions
resource "aws_cloudwatch_log_group" "step_functions_log_group" {
  name              = "/aws/stepfunctions/agentcore-hitl-workflow"
  retention_in_days = 14

  tags = {
    Name        = "agentcore-stepfunctions-logs"
    Environment = var.environment
  }
}

# Step Functions State Machine for HITL Workflow
resource "aws_sfn_state_machine" "agentcore_hitl_workflow" {
  name     = "agentcore-hitl-workflow"
  role_arn = aws_iam_role.step_functions_execution_role.arn

  definition = jsonencode({
    Comment = "AgentCore Human-in-the-Loop Approval Workflow"
    StartAt = "RequestApproval"
    States = {
      RequestApproval = {
        Type     = "Task"
        Resource = aws_lambda_function.agentcore_hitl_approval.arn
        Parameters = {
          "Input.$" = "$"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 2
            MaxAttempts     = 6
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.TaskFailed"]
            Next        = "ApprovalFailed"
          },
          {
            ErrorEquals = ["States.ALL"]
            Next        = "ApprovalFailed"
          }
        ]
        Next = "CheckApprovalStatus"
      }
      CheckApprovalStatus = {
        Type = "Choice"
        Choices = [
          {
            Variable      = "$.body.status"
            StringEquals  = "approve"
            Next          = "ApprovalGranted"
          },
          {
            Variable      = "$.body.status"
            StringEquals  = "reject"
            Next          = "ApprovalRejected"
          },
          {
            Variable      = "$.body.status"
            StringEquals  = "failed"
            Next          = "ApprovalFailed"
          }
        ]
        Default = "WaitForApproval"
      }
      WaitForApproval = {
        Type    = "Wait"
        Seconds = 30
        Next    = "RequestApproval"
      }
      ApprovalGranted = {
        Type   = "Pass"
        Result = {
          status  = "approved"
          message = "Request has been approved"
        }
        End = true
      }
      ApprovalRejected = {
        Type   = "Pass"
        Result = {
          status  = "rejected"
          message = "Request has been rejected"
        }
        End = true
      }
      ApprovalFailed = {
        Type   = "Pass"
        Result = {
          status  = "failed"
          message = "Approval process failed"
        }
        End = true
      }
    }
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_functions_log_group.arn}:*"
    include_execution_data = true
    level                 = "ERROR"
  }

  tags = {
    Name        = "agentcore-hitl-workflow"
    Environment = var.environment
  }
}

# EventBridge Rule for triggering workflows
resource "aws_cloudwatch_event_rule" "agentcore_trigger" {
  name        = "agentcore-hitl-trigger"
  description = "Trigger AgentCore HITL workflow"

  event_pattern = jsonencode({
    source      = ["agentcore.application"]
    detail-type = ["Agent Action Request"]
    detail = {
      requires_approval = ["true"]
    }
  })

  tags = {
    Name        = "agentcore-trigger"
    Environment = var.environment
  }
}

# EventBridge Target for Step Functions
resource "aws_cloudwatch_event_target" "step_functions_target" {
  rule      = aws_cloudwatch_event_rule.agentcore_trigger.name
  target_id = "AgentCoreStepFunctionsTarget"
  arn       = aws_sfn_state_machine.agentcore_hitl_workflow.arn
  role_arn  = aws_iam_role.eventbridge_role.arn
}

# IAM Role for EventBridge to invoke Step Functions
resource "aws_iam_role" "eventbridge_role" {
  name = "agentcore-eventbridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "events.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "agentcore-eventbridge-role"
    Environment = var.environment
  }
}

# IAM Policy for EventBridge to invoke Step Functions
resource "aws_iam_policy" "eventbridge_stepfunctions_policy" {
  name        = "agentcore-eventbridge-stepfunctions-policy"
  description = "IAM policy for EventBridge to invoke Step Functions"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution"
        ]
        Resource = aws_sfn_state_machine.agentcore_hitl_workflow.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "eventbridge_stepfunctions_policy_attachment" {
  role       = aws_iam_role.eventbridge_role.name
  policy_arn = aws_iam_policy.eventbridge_stepfunctions_policy.arn
} 