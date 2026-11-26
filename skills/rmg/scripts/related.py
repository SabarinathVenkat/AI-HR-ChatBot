"""Skills that a resume shows only indirectly: what in a resume genuinely implies a skill the job description names.

A resume that says "Spring Boot" does show "Spring"; one that says "JUnit" shows "unit testing"; "Jenkins" shows "CI/CD". These are
the only inferences the RMG skill may make on its own, because the candidate can truthfully stand behind them in an interview.
A skill with no such evidence in the resume is a gap, and only the candidate can claim it.

Keep this list strict. Add a pair only if anyone who has done the left side has necessarily done the right side. "Works with AWS"
does not imply "Kubernetes", and "knows Java" does not imply "Spring".

Used by check_claims.py (to accept an --inferred skill) and match_level.py (to find what can be mapped).
"""
import re

# skill the JD names -> things in the resume that really show it
EVIDENCE: dict[str, tuple[str, ...]] = {
    "spring": ("Spring Boot", "Spring MVC", "Spring Cloud", "Spring Data", "Spring Security"),
    "rest": ("RESTful", "REST API", "REST APIs", "Web API", "ASP.NET Web API", "JAX-RS", "Spring MVC", "Express"),
    "rest apis": ("RESTful", "REST", "Web API", "ASP.NET Web API", "JAX-RS"),
    "unit testing": ("JUnit", "NUnit", "xUnit", "pytest", "unittest", "Jest", "Mockito", "Mocha", "TestNG"),
    "automated testing": ("JUnit", "NUnit", "xUnit", "pytest", "Jest", "Selenium", "Cypress", "Playwright", "TestNG"),
    "ci/cd": ("Jenkins", "GitHub Actions", "GitLab CI", "Azure DevOps", "CircleCI", "TeamCity", "Bamboo", "Travis CI"),
    "devops": ("Jenkins", "Docker", "Kubernetes", "Terraform", "Ansible", "GitHub Actions", "Azure DevOps", "CI/CD"),
    "rdbms": ("SQL Server", "PostgreSQL", "MySQL", "Oracle", "MariaDB", "Postgres", "SQLite"),
    "sql": ("SQL Server", "PostgreSQL", "MySQL", "Oracle", "MariaDB", "Postgres", "SQLite", "T-SQL", "PL/SQL"),
    "oop": ("Java", "C#", "C++", ".NET", "Kotlin", "Scala"),
    "messaging": ("Kafka", "RabbitMQ", "SQS", "SNS", "ActiveMQ", "Azure Service Bus", "Pub/Sub"),
    "observability": ("Datadog", "New Relic", "Prometheus", "Grafana", "Splunk", "Dynatrace", "Elastic", "ELK", "OpenTelemetry"),
    "apm": ("Datadog", "New Relic", "Dynatrace", "AppDynamics", "Application Insights"),
    "agile": ("Scrum", "Kanban", "Sprint", "SAFe"),
    "cloud platforms": ("AWS", "Azure", "GCP", "Google Cloud"),
    "cloud-native architecture": ("Kubernetes", "AWS Lambda", "Azure Functions", "Cloud Run"),
    "cloud storage": ("S3", "Blob Storage", "Cloud Storage", "GCS"),
    "microservices": ("Spring Cloud", "service mesh", "Istio"),
    "ai-assisted development": ("GitHub Copilot", "Copilot", "Cursor", "Claude Code"),
    "api design": ("REST API", "REST APIs", "RESTful", "OpenAPI", "Swagger", "GraphQL"),
    "version control": ("Git", "GitHub", "GitLab", "Bitbucket", "SVN"),
    "containers": ("Docker", "Kubernetes", "Podman"),
    "orchestration": ("Kubernetes", "Airflow", "Step Functions"),
}


def _mentions(text: str, term: str) -> bool:
    words = term.split()
    pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(w) for w in words) + r"(?![A-Za-z0-9+#])"
    return re.search(pattern, text, re.IGNORECASE) is not None


def evidence_for(skill: str, text: str) -> list[str]:
    """The things in `text` (the resume) that genuinely show `skill`, or an empty list if there are none."""
    terms = EVIDENCE.get(" ".join(skill.casefold().split()), ())
    return [t for t in terms if _mentions(text, t)]
