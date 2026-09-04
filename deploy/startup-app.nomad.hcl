variable "image" {
  type = string
}

variable "hostname" {
  type = string
}

variable "revision" {
  type = string
}

job "startup-app" {
  datacenters = ["cs403bkk"]
  namespace   = "startup"
  type        = "service"

  group "web" {
    count = 1

    network {
      port "http" {
        to = 8000
      }
    }

    task "app" {
      driver = "docker"

      config {
        image = var.image
        ports = ["http"]
      }

      env {
        APP_REVISION = var.revision
      }

      resources {
        cpu    = 300
        memory = 256
      }

      service {
        name     = "startup-app"
        port     = "http"
        provider = "nomad"

        tags = [
          "traefik.enable=true",
          format("traefik.http.routers.startup-app.rule=Host(`%s`)", var.hostname),
          "traefik.http.routers.startup-app.entrypoints=websecure",
          "traefik.http.routers.startup-app.tls=true",
          "traefik.http.routers.startup-app.tls.certresolver=letsencrypt",
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
