terraform {
  required_version = ">= 1.13.0, < 1.14.0"

  required_providers {
    citrixadc = {
      source  = "registry.terraform.io/citrix/citrixadc"
      version = "= 2.3.0"
    }
  }

  backend "local" {}
}
