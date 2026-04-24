resource "aws_db_subnet_group" "main" {
  name       = "aec-${var.environment}-db"
  subnet_ids = aws_subnet.private[*].id
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db" {
  name = "aec/${var.environment}/db"
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db.result
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
  })
}

resource "aws_db_parameter_group" "pg15" {
  name   = "aec-${var.environment}-pg15"
  family = "postgres15"
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,vector"
    apply_method = "pending-reboot"
  }
}

resource "aws_db_instance" "main" {
  identifier              = "aec-${var.environment}"
  engine                  = "postgres"
  engine_version          = "15"
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_storage_gb
  storage_encrypted       = true
  db_name                 = "aec"
  username                = var.db_username
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  parameter_group_name    = aws_db_parameter_group.pg15.name
  backup_retention_period = 14
  deletion_protection     = var.environment == "prod"
  skip_final_snapshot     = var.environment != "prod"
  multi_az                = var.environment == "prod"
  publicly_accessible     = false
  performance_insights_enabled = true
}
