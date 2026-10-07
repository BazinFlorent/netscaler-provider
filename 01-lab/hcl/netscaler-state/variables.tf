variable "vip" {
  description = "Adresse Docker de CPX utilisée comme VIP dans le lab."
  type        = string
}

variable "lb_port" {
  description = "Port interne du virtual server."
  type        = number
  default     = 8080
}

variable "lb_method" {
  description = "Méthode de répartition."
  type        = string
  default     = "ROUNDROBIN"
}

variable "backends" {
  description = "Membres du pool, identifiés par une clé logique stable."
  type = map(object({
    ip   = string
    port = number
  }))
}

variable "lb_name" {
  description = "Nom du virtual server NetScaler."
  type        = string
}

variable "pool_name" {
  description = "Nom du service group NetScaler."
  type        = string
}
