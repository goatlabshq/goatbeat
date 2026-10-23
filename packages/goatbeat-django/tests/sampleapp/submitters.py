from goatbeat.core.execution import SubmissionReceipt
from goatbeat.core.submission import TaskSubmission

SUBMITTED: list[str] = []


class RecordingSubmitter:
    def submit(self, submission: TaskSubmission) -> SubmissionReceipt:
        SUBMITTED.append(submission.task.path)
        return SubmissionReceipt(submission.idempotency_key.value)


recording = RecordingSubmitter()
not_a_submitter = 42
