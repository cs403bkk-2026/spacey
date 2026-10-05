# Request log to stdout so it reaches Loki. %(U)s is the path without the
# query string, and the referer is left out, because URLs can carry values
# that must not be logged (secrets like the door access code never go in URLs).
accesslog = "-"
access_log_format = '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s %(M)sms "%(a)s"'
