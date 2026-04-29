from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task


@CrewBase
class EngineeringTeam:
    """AutoDev Crew: a dynamic multi-agent software engineering workflow.

    AutoDev Crew keeps the expanded SDLC-style agent group and supports both CLI and
    Gradio dashboard execution. Deterministic validation, test execution,
    and optional repair run after the crew finishes generation.
    """

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @agent
    def product_manager(self) -> Agent:
        return Agent(
            config=self.agents_config["product_manager"],
            verbose=True,
        )

    @agent
    def solution_architect(self) -> Agent:
        return Agent(
            config=self.agents_config["solution_architect"],
            verbose=True,
        )

    @agent
    def engineering_lead(self) -> Agent:
        return Agent(
            config=self.agents_config["engineering_lead"],
            verbose=True,
        )

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["backend_engineer"],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",  # Uses Docker for safer execution.
            max_execution_time=500,
            max_retry_limit=3,
        )

    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["frontend_engineer"],
            verbose=True,
        )

    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config["test_engineer"],
            verbose=True,
            allow_code_execution=True,
            code_execution_mode="safe",  # Uses Docker for safer execution.
            max_execution_time=500,
            max_retry_limit=3,
        )

    @agent
    def code_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["code_reviewer"],
            verbose=True,
        )

    @agent
    def security_reviewer(self) -> Agent:
        return Agent(
            config=self.agents_config["security_reviewer"],
            verbose=True,
        )

    @agent
    def documentation_agent(self) -> Agent:
        return Agent(
            config=self.agents_config["documentation_agent"],
            verbose=True,
        )

    @task
    def product_spec_task(self) -> Task:
        return Task(config=self.tasks_config["product_spec_task"])

    @task
    def architecture_task(self) -> Task:
        return Task(config=self.tasks_config["architecture_task"])

    @task
    def design_task(self) -> Task:
        return Task(config=self.tasks_config["design_task"])

    @task
    def code_task(self) -> Task:
        return Task(config=self.tasks_config["code_task"])

    @task
    def frontend_task(self) -> Task:
        return Task(config=self.tasks_config["frontend_task"])

    @task
    def test_task(self) -> Task:
        return Task(config=self.tasks_config["test_task"])

    @task
    def code_review_task(self) -> Task:
        return Task(config=self.tasks_config["code_review_task"])

    @task
    def security_review_task(self) -> Task:
        return Task(config=self.tasks_config["security_review_task"])

    @task
    def documentation_task(self) -> Task:
        return Task(config=self.tasks_config["documentation_task"])

    @crew
    def crew(self) -> Crew:
        """Create the sequential SDLC crew."""
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )
