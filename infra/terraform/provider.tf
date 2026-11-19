terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 2.0"
    }
  }
}

provider "mongodbatlas" {
  client_id     = var.mongodb_client_id
  client_secret = var.mongodb_client_secret
}
