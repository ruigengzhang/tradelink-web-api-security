# Optional OWASP ZAP baseline

From the repository root, start Docker and run:

```sh
docker compose -f zap/compose.yml run --rm zap
docker compose -f zap/compose.yml down
```

Compose starts a fresh copy of the fixed Flask application with synthetic records. The scanner shares its network namespace and reaches loopback without publishing any ports. The baseline spiders public pages and passively inspects responses. The configuration marks missing anti-clickjacking, content-type and CSP headers as failures. Review `zap/report.html` and the terminal output. ZAP uses exit code 1 for a configured failure, 2 for warnings and 3 for execution errors. [ZAP Baseline documentation](https://www.zaproxy.org/docs/docker/baseline-scan/)

This scan is unauthenticated. Use the paired-request lab and pytest to assess tenant isolation, function authorization and private response fields.
