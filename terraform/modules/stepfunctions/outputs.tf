output "step_functions_arn" {
  description = "ARN of the AgentCore HITL Step Functions state machine"
  value       = aws_sfn_state_machine.agentcore_hitl_workflow.arn
}

output "step_functions_name" {
  description = "Name of the AgentCore HITL Step Functions state machine"
  value       = aws_sfn_state_machine.agentcore_hitl_workflow.name
}

output "eventbridge_rule_name" {
  description = "Name of the EventBridge rule for triggering workflows"
  value       = aws_cloudwatch_event_rule.agentcore_trigger.name
}

output "step_functions_log_group_name" {
  description = "Name of the Step Functions CloudWatch log group"
  value       = aws_cloudwatch_log_group.step_functions_log_group.name
} 