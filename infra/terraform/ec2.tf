data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_instance" "mergency" {
  ami                    = data.aws_ssm_parameter.al2023_ami.value
  instance_type          = var.instance_type
  key_name               = aws_key_pair.mergency.key_name
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.mergency.id]
  user_data              = file("${path.module}/user_data.sh")

  tags = {
    Name    = "mergency-dogfood"
    Project = "mergency"
  }
}

resource "aws_eip" "mergency" {
  instance = aws_instance.mergency.id
  domain   = "vpc"

  tags = {
    Name = "mergency-dogfood"
  }
}
