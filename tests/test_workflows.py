"""Guards for the GitHub Actions files, since they can only be exercised on GitHub."""
import glob
import os
import re
import subprocess
import unittest

import yaml

import helpers

WORKFLOWS = os.path.join(helpers.ROOT, ".github", "workflows")


def load(name):
    with open(os.path.join(WORKFLOWS, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def steps(workflow):
    return workflow["jobs"][next(iter(workflow["jobs"]))]["steps"]


def step(workflow, fragment):
    return next(s for s in steps(workflow) if fragment.lower() in (s.get("name") or s.get("uses") or "").lower())


class DailyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.wf = load("daily.yml")
        self.text = open(os.path.join(WORKFLOWS, "daily.yml"), encoding="utf-8").read()

    def test_it_runs_every_day_and_can_be_started_by_hand(self):
        on = self.wf[True] if True in self.wf else self.wf["on"]          # YAML reads a bare `on` as True
        cron = on["schedule"][0]["cron"]
        self.assertEqual(len(cron.split()), 5)
        self.assertEqual(cron.split()[2:], ["*", "*", "*"])                # every day of every month
        self.assertIn("subject", on["workflow_dispatch"]["inputs"])
        self.assertIn("topics", on["workflow_dispatch"]["inputs"])

    def test_the_api_key_secret_has_the_exact_name_the_code_reads(self):
        env = step(self.wf, "Run analysis")["env"]
        self.assertEqual(env["ANTHROPIC_API_KEY"], "${{ secrets.ANTHROPIC_API_KEY }}")

    def env_names_in(self, *relative):
        found = set()
        for rel in relative:
            for path in glob.glob(os.path.join(helpers.ROOT, rel), recursive=True):
                src = open(path, encoding="utf-8").read()
                found |= set(re.findall(r'environ\.get\("([A-Z][A-Z_]+)"', src))
                found |= set(re.findall(r'api_key_env="([A-Z][A-Z_]+)"', src))
        return found

    def test_every_environment_variable_the_analysis_needs_is_passed_to_that_step(self):
        needed = self.env_names_in("trendwatch/*.py", "trendwatch/llm/*.py", "trendwatch/sources/*.py") - {"OPENAI_API_KEY"}
        needed -= self.env_names_in("trendwatch/emailer.py")
        env = step(self.wf, "Run analysis")["env"]
        self.assertTrue({"ANTHROPIC_API_KEY", "BSKY_HANDLE", "BSKY_APP_PASSWORD"} <= needed, needed)
        for name in needed:
            self.assertIn(name, env, f"{name} is read by the code but not passed by the workflow")
            self.assertIn(f"secrets.{name}", env[name])

    def test_every_environment_variable_the_emailer_reads_is_passed_to_the_email_step(self):
        needed = self.env_names_in("trendwatch/emailer.py")
        self.assertTrue({"SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_HOST", "SMTP_PORT", "MAIL_FROM"} <= needed, needed)
        env = step(self.wf, "Email the report")["env"]
        for name in needed:
            self.assertEqual(env.get(name), "${{ secrets." + name + " }}", name)

    def test_the_mail_credentials_are_only_given_to_the_email_step(self):
        for st in steps(self.wf):
            if st.get("name") != "Email the report":
                self.assertNotIn("SMTP_PASSWORD", yaml.dump(st), st.get("name"))

    def test_the_email_goes_out_last_after_the_results_are_committed(self):
        names = [s.get("name", s.get("uses", "")) for s in steps(self.wf)]
        self.assertEqual(names[-2:], ["Commit results", "Email the report"])
        self.assertEqual(step(self.wf, "Email the report")["run"], "python send_report.py")

    def test_scheduled_runs_always_email_and_manual_runs_can_opt_out(self):
        condition = step(self.wf, "Email the report")["if"]
        self.assertIn("github.event_name == 'schedule'", condition)
        self.assertIn("github.event.inputs.send_email != 'false'", condition)
        self.assertIn("success()", condition)
        on = self.wf[True] if True in self.wf else self.wf["on"]
        self.assertTrue(on["workflow_dispatch"]["inputs"]["send_email"]["default"])

    def test_a_missing_secret_fails_early_with_a_clear_message(self):
        names = [s.get("name", "") for s in steps(self.wf)]
        self.assertLess(names.index("Check the API key secret exists"), names.index("Run analysis"))
        script = step(self.wf, "Check the API key").get("run")
        self.assertIn('-z "$ANTHROPIC_API_KEY"', script)
        self.assertIn("::error::", script)
        self.assertIn("exit 1", script)

    def test_the_timeout_leaves_room_for_a_full_run(self):
        timeout = self.wf["jobs"]["report"]["timeout-minutes"]
        self.assertGreaterEqual(timeout, 45)
        self.assertLessEqual(timeout, 360)

    def test_two_runs_can_never_overlap(self):
        self.assertEqual(self.wf["concurrency"]["group"], "daily-report")
        self.assertFalse(self.wf["concurrency"]["cancel-in-progress"])

    def test_it_may_push_the_results_back(self):
        self.assertEqual(self.wf["permissions"], {"contents": "write"})
        commit = step(self.wf, "Commit results")["run"]
        self.assertIn("git add data", commit)
        self.assertIn("git diff --staged --quiet ||", commit)             # no empty commits
        self.assertIn("git push", commit)
        names = [s.get("name", s.get("uses", "")) for s in steps(self.wf)]
        self.assertLess(names.index("Run analysis"), names.index("Commit results"))   # only after the analysis succeeded

    def test_python_dependencies_come_from_requirements_and_the_version_is_supported(self):
        self.assertIn("pip install -r requirements.txt", self.text)
        setup = step(self.wf, "setup-python")
        self.assertEqual(setup["with"]["python-version"], "3.12")
        self.assertEqual(setup["with"]["cache"], "pip")

    def test_user_supplied_inputs_reach_the_shell_through_environment_variables_only(self):
        for run in (s.get("run", "") for s in steps(self.wf)):
            self.assertNotIn("${{ github.event.inputs", run)

    def test_the_run_script_builds_the_right_command_line(self):
        script = step(self.wf, "Run analysis")["run"].replace("python run.py", "printf '%s|' run.py")
        def run(**env):
            out = subprocess.run(["bash", "-c", script], capture_output=True, text=True,
                                 env={"PATH": os.environ["PATH"], **env})
            self.assertEqual(out.returncode, 0, out.stderr)
            return out.stdout
        self.assertEqual(run(SUBJECT="", TOPICS=""), "run.py|")                         # the scheduled run
        self.assertEqual(run(SUBJECT="Iran war", TOPICS=""), "run.py|--subject|Iran war|")
        self.assertEqual(run(SUBJECT="", TOPICS="5"), "run.py|--topics|5|")
        self.assertEqual(run(SUBJECT="a b; echo pwned", TOPICS="3"),        # a hostile subject stays one argument
                         "run.py|--subject|a b; echo pwned|--topics|3|")

    def test_the_summary_step_does_not_fail_when_there_is_no_report(self):
        script = step(self.wf, "job summary")["run"]
        out = subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd="/",
                             env={"PATH": os.environ["PATH"], "GITHUB_STEP_SUMMARY": os.devnull})
        self.assertEqual(out.returncode, 0, out.stderr)

    def test_the_html_report_is_kept_as_an_artifact(self):
        upload = step(self.wf, "downloadable")
        self.assertTrue(upload["uses"].startswith("actions/upload-artifact@v"))
        self.assertEqual(upload["with"]["path"], "data/reports/*.html")


class TestsWorkflowTests(unittest.TestCase):
    def test_the_test_workflow_needs_no_secrets_and_runs_the_whole_suite(self):
        wf = load("tests.yml")
        text = open(os.path.join(WORKFLOWS, "tests.yml"), encoding="utf-8").read()
        self.assertNotIn("secrets.", text)
        self.assertIn("python -m unittest discover -s tests", text)
        on = wf[True] if True in wf else wf["on"]
        self.assertIn("push", on)


if __name__ == "__main__":
    unittest.main()
