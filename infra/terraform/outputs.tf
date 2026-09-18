output "instance_public_ip" {
  value = aws_eip.mergency.public_ip
}

output "ssh_command" {
  value = "ssh -A -i ~/.ssh/mergency-aws ec2-user@${aws_eip.mergency.public_ip}"
}

output "webhook_url" {
  value = "http://${aws_eip.mergency.public_ip}:8000/webhooks/github"
}
