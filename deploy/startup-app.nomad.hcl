variable "image" {
  type = string
}

variable "hostname" {
  type = string
}

variable "revision" {
  type = string
}

job "spacey" {
  datacenters = ["cs403bkk"]
  namespace   = "startup"
  type        = "service"

  group "web" {
    count = 1

    constraint {
      attribute = "${node.unique.name}"
      value     = "cs403bkk-nomad-1"
    }

    update {
      max_parallel      = 1
      health_check      = "checks"
      min_healthy_time  = "10s"
      healthy_deadline  = "3m"
      progress_deadline = "5m"
      auto_revert       = true
    }

    restart {
      attempts = 3
      interval = "5m"
      delay    = "10s"
      mode     = "fail"
    }

    network {
      port "http" {
        to = 8000
      }
    }

    task "spacey" {
      driver = "docker"

      config {
        image = var.image
        ports = ["http"]
        # PUR-025: in a container, the public name resolves to the server's
        # public IP, which refuses container traffic. Resolve it to the
        # proxy's private address (node cs403bkk-nomad-1), which serves it
        # with the same certificate and is reachable from every node.
        extra_hosts = ["purchase.cs403bkk26.space:192.168.171.100"]
      }

      env {
        APP_REVISION = var.revision
      }

      template {
        data        = <<EOH
DATABASE_URL={{ with nomadVar "nomad/jobs/spacey" }}{{ .database_url }}{{ end }}
PURCHASE_URL={{ with nomadVar "nomad/jobs/spacey" }}{{ with .purchase_url }}{{ . }}{{ end }}{{ end }}
PURCHASE_TOKEN={{ with nomadVar "nomad/jobs/spacey" }}{{ with .purchase_token }}{{ . }}{{ end }}{{ end }}
ACCESS_URL={{ with nomadVar "nomad/jobs/spacey" }}{{ with .access_url }}{{ . }}{{ end }}{{ end }}
SERVICE_TOKEN={{ with nomadVar "nomad/jobs/spacey" }}{{ with .access_token }}{{ . }}{{ end }}{{ end }}
EOH
        destination = "secrets/runtime.env"
        env         = true
        change_mode = "restart"
      }

      resources {
        cpu    = 300
        memory = 256
      }

      service {
        name     = "spacey"
        port     = "http"
        provider = "nomad"

        tags = [
          "traefik.enable=true",
          format("traefik.http.routers.spacey.rule=Host(`%s`)", var.hostname),
          "traefik.http.routers.spacey.entrypoints=websecure",
          "traefik.http.routers.spacey.tls=true",
          "traefik.http.routers.spacey.tls.certresolver=letsencrypt",
        ]

        check {
          type     = "http"
          path     = "/health"
          interval = "10s"
          timeout  = "2s"
        }
      }
    }
  }
}
