resource "aws_key_pair" "mergency" {
  key_name   = "mergency-dogfood"
  public_key = file(var.public_key_path)
}
