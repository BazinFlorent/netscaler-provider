resource "citrixadc_lbvserver" "http" {
  name            = var.lb_name
  servicetype     = "HTTP"
  ipv46           = var.vip
  port            = var.lb_port
  lbmethod        = var.lb_method
  persistencetype = "NONE"
}

resource "citrixadc_servicegroup" "http" {
  servicegroupname = var.pool_name
  servicetype      = "HTTP"
}

resource "citrixadc_servicegroup_servicegroupmember_binding" "backend" {
  for_each = var.backends

  servicegroupname = citrixadc_servicegroup.http.servicegroupname
  ip               = each.value.ip
  port             = each.value.port
}

resource "citrixadc_lbvserver_servicegroup_binding" "http" {
  name             = citrixadc_lbvserver.http.name
  servicegroupname = citrixadc_servicegroup.http.servicegroupname

  lifecycle {
    replace_triggered_by = [
      citrixadc_lbvserver.http.port
    ]
  }
}
