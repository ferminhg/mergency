variable "aws_region" {
  description = "The AWS region to deploy resources in."
  type        = string
  default     = "eu-north-1"
}

variable "instance_type" {
  description = "The EC2 instance type to use for the application."
  type        = string
  default     = "t3.micro"
}

variable "ssh_allowed_cidr" {
  description = "The CIDR block that is allowed to SSH into the EC2 instance."
  type        = string
}

variable "public_key_path" {
  description = "The path to the public key file for SSH access."
  type        = string
  default     = "~/.ssh/mergency-aws.pub"
}
