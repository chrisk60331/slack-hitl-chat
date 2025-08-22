# CloudWatch Log Group for Step Functions
resource "aws_cloudwatch_log_group" "step_functions_log_group" {
  name              = "/aws/stepfunctions/${var.name_prefix}-hitl-workflow"
  retention_in_days = 14

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-stepfunctions-logs"
  })
}

# Step Functions State Machine for HITL Workflow
resource "aws_sfn_state_machine" "agentcore_hitl_workflow" {
  name     = "${var.name_prefix}-hitl-workflow"
  role_arn = var.step_functions_execution_role_arn

  definition = jsonencode({
    Comment = "AgentCore Human-in-the-Loop Approval Workflow"
    StartAt = "RequestApproval"
    States = {
      RequestApproval = {
        Type     = "Task"
        Resource = var.lambda_function_arn
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
            Next          = "NotifyCompletion"
          },
          {
            Variable      = "$.body.status"
            StringEquals  = "pending"
            Next          = "WaitForApproval"
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
        Parameters = {
          "status" = "approved"
          "message" = "Request has been approved"
          "request_id.$" = "$.body.request_id"
        }
        Next = "ExecuteApprovedAction"
      }
      ApprovalRejected = {
        Type   = "Pass"
        Parameters = {
          "status" = "rejected"
          "message" = "Request has not been approved"
          "request_id.$" = "$.body.request_id"
          "execute_result" = "Request Rejected by Human."
        }
        Next = "NotifyCompletion"
      }
      ExecuteApprovedAction = {
        Type     = "Task"
        Resource = var.execute_lambda_function_arn
        Parameters = {
          "request_id.$" = "$.request_id"
          "execution_timeout" = 300
        }
        ResultPath = "$.execute_result"
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.TaskFailed"]
            Next        = "ExecutionFailed"
          },
          {
            ErrorEquals = ["States.ALL"]
            Next        = "ExecutionFailed"
          }
        ]
        Next = "NotifyCompletion"
      }
      NotifyCompletion = {
        Type     = "Task"
        Resource = var.completion_lambda_function_arn
        Parameters = {
          "request_id.$" = "$.request_id"
          "result.$"     = "$.execute_result"
        }
        Retry = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException"]
            IntervalSeconds = 2
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            Next        = "ExecutionComplete"
          }
        ]
        Next = "ExecutionComplete"
      }
      ExecutionComplete = {
        Type   = "Pass"
        Result = {
          status  = "completed"
          message = "Request approved and executed successfully"
        }
        End = true
      }
      ExecutionFailed = {
        Type   = "Pass"
        Result = {
          status  = "execution_failed"
          message = "Request was approved but execution failed"
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

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-hitl-workflow"
  })
}

# EventBridge Rule for triggering workflows
resource "aws_cloudwatch_event_rule" "agentcore_trigger" {
  name        = "${var.name_prefix}-hitl-trigger"
  description = "Trigger AgentCore HITL workflow"

  event_pattern = jsonencode({
    source      = ["agentcore.application"]
    detail-type = ["Agent Action Request"]
    detail = {
      requires_approval = ["true"]
    }
  })

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-trigger"
  })
}

# EventBridge Target for Step Functions
resource "aws_cloudwatch_event_target" "step_functions_target" {
  rule      = aws_cloudwatch_event_rule.agentcore_trigger.name
  target_id = "AgentCoreStepFunctionsTarget"
  arn       = aws_sfn_state_machine.agentcore_hitl_workflow.arn
  role_arn  = var.eventbridge_role_arn
}

# Lambda permission for Step Functions (approval lambda)
resource "aws_lambda_permission" "step_functions_lambda" {
  statement_id  = "AllowExecutionFromStepFunctions"
  action        = "lambda:InvokeFunction"
  function_name = var.lambda_function_name
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.agentcore_hitl_workflow.arn
}

# Lambda permission for Step Functions (execute lambda)
resource "aws_lambda_permission" "step_functions_execute_lambda" {
  statement_id  = "AllowExecutionFromStepFunctionsExecute"
  action        = "lambda:InvokeFunction"
  function_name = var.execute_lambda_function_arn
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.agentcore_hitl_workflow.arn
} 

# Lambda permission for Step Functions (completion notifier)
resource "aws_lambda_permission" "step_functions_completion_lambda" {
  statement_id  = "AllowExecutionFromStepFunctionsCompletion"
  action        = "lambda:InvokeFunction"
  function_name = var.completion_lambda_function_arn
  principal     = "states.amazonaws.com"
  source_arn    = aws_sfn_state_machine.agentcore_hitl_workflow.arn
}