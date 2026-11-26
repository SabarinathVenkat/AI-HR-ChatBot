# Test report: match levels, badges, format guard (26 November 2026)

What was tested: the RMG skill's three match levels (Mirror, Bridge, Summit) and its scripts, badge extraction and placement, and the
app's format guard, using made-up data. Plain text, no tables.

## 1. The dummy data

One job description: "Senior Backend Engineer (Payments)".
- Must-have (10): Java, Spring Boot, REST APIs, Kafka, PostgreSQL, Docker, Kubernetes, CI/CD, Terraform, AWS.
- Nice-to-have (3): Redis, GraphQL, Datadog.

Three made-up candidates, each with two projects, and a Word resume with badge pictures in its header:
- Asha Verma, strong fit (Java, Spring Boot, RESTful services, Kafka, PostgreSQL, Docker, Jenkins, AWS). 2 badges.
- Ben Carter, partial fit (Java, Spring MVC, MySQL, Jenkins). 1 badge.
- Chitra Rao, weak fit (.NET, ASP.NET Web API, SQL Server, Azure DevOps). 3 badges.

Files are in var/dummy/ (not committed): the resumes, the tailored text for each level, the badge pictures, the final Word files, and
results.json with every number below.

## 2. What the tailoring was (important)

The tailoring was done by a scripted stand-in that follows the playbook rules mechanically, because the real tailoring is Claude's
writing and cannot be run from a test. So this run tests the scripts, the numbers and the guardrails. It does not test how well
Claude writes the bullets, and the skill has not been run end to end in Claude Desktop.

## 3. Results by candidate and level (must-have skills shown)

Asha Verma, 60 percent as she is:
- Mirror: 60 percent. Nothing added. Checker passed.
- Bridge (target 50): 80 percent. Two skills inferred from evidence, REST APIs (from RESTful) and CI/CD (from Jenkins). None added.
  Checker passed.
- Summit (target 80): 80 percent, reached by the same two inferred skills. Nothing added without evidence. Checker passed.

Ben Carter, 10 percent as he is:
- Mirror: 10 percent. Nothing added. Checker passed.
- Bridge: 50 percent. CI/CD inferred (from Jenkins). Three added for the match: Spring Boot, REST APIs, Kafka. The checker passed and
  printed one WARNING line per added skill.
- Summit: 80 percent. CI/CD inferred, Terraform confirmed by the candidate (simulated answer), and five added for the match: Spring
  Boot, REST APIs, Kafka, PostgreSQL, Docker. Checker passed with warnings.

Chitra Rao, 0 percent as she is:
- Mirror: 0 percent. Nothing added. Checker passed.
- Bridge: 50 percent. REST APIs (from Web API) and CI/CD (from Azure DevOps) inferred, three added: Java, Spring Boot, Kafka.
- Summit: 80 percent. Two inferred, six added: Java, Spring Boot, Kafka, PostgreSQL, Docker, Kubernetes.

Every level reached its target for every candidate, Mirror never changed a percentage, and the number of skills added without
evidence was exactly what the target needed (Asha: none, Ben: 3 then 5 plus one confirmed, Chitra: 3 then 6).

## 4. Guardrail checks (the checker must refuse these)

- A skill the resume does not show (Kubernetes) written in without being listed: refused.
- An invented number ("cut latency by 73 percent"): refused.
- An invented technology name (Zorblax): refused.
- A skill listed as inferred but with no evidence in the resume (Terraform for Asha): refused.
- The same Terraform line listed as added for the match: accepted, with a WARNING line saying the candidate must approve it.

All five behaved as designed. Added skills did not excuse a made-up number or technology: a separate unit test covers that.

## 5. Badges and the template

For each dummy resume: badges found in the header, extracted as clean PNG files, and placed in the real company template's
header cell, right-aligned.
- Asha: 2 in the resume, 2 extracted, 2 placed (0.68 inch each).
- Ben: 1, 1, 1 placed.
- Chitra: 3, 3, 3 placed (0.64 inch each, sized to fit one row).

## 6. The app's format guard and template check

The three candidates were rendered by the app into the real Ideas2IT template with their badges.
- Format fixes needed: none for all three (the normal render already keeps the template's format).
- Template check: pass for all three, no problems.
- Separate unit tests damage a finished file (margins, a centred bullet, a stray font and size) and check the template's settings
  come back and the words do not change: all pass. A run on the real template restored all of it.

## 7. Automated test suites

- Unit tests: 1189 collected, all pass (includes 32 skill tests and 9 format guard tests).
- Integration tests: 180, all pass.
- Resume browser tests: 37, all pass.
- Ruff (code style check): clean.
A full run of everything at once was stopped earlier by low memory, so the suites were run in groups.

## 8. Findings and risks

1. Which skills get added is the biggest risk. When no evidence exists, the stand-in adds must-haves in the JD's order, so a .NET
   developer (Chitra) at Summit gets Java, Spring Boot, Kafka, PostgreSQL, Docker and Kubernetes. That reaches 80 percent and the
   warning and note are produced, but it is a very different person from the one in the file. The candidate approval is then the only
   protection. Suggested fix: add the closest skills first (PostgreSQL for a SQL Server developer, Docker, AWS) and refuse a
   level that needs more than a set number of additions without asking, instead of filling in JD order.
2. At Bridge, a resume already at 60 percent (Asha) still got its evidence-backed skills written in (to 80 percent). That is allowed
   and harmless, but it means "at least 50" can finish higher than 50.
3. Mirror, Bridge and Summit exist only in the skill. The app still has Polish and Deep match and still refuses to add skills the
   resume does not show.
4. The match percentage on the earlier real case (26 percent, the .NET manager JD) was mostly real gaps: 9 of 35 must-haves. The
   matcher fix (spellings, ".NET/C#") only lifts such a number by a few points.

## 9. Not tested

- Claude's own writing for any level, and the skill inside Claude Desktop.
- The finished files opened in Word, or drawn to pages with LibreOffice (layout was checked in code and, earlier, on the real sample).
- The new code on the RunPod pod: it has not been built into an image or deployed.
