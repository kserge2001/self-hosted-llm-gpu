import unittest

from plan_cleanup import selection, verify_plan


def resource(address, kind, mode="managed"):
    return {"address": address, "type": kind, "mode": mode}


class CleanupPlanTests(unittest.TestCase):
    def test_preserves_evidence_and_keys_in_nested_modules(self):
        state = {"values": {"root_module": {"resources": [
            resource("aws_s3_bucket.evidence", "aws_s3_bucket"),
            resource("aws_db_instance.gateway", "aws_db_instance"),
            resource("data.aws_route53_zone.existing", "aws_route53_zone", "data")],
            "child_modules": [{"resources": [resource("module.eks.aws_kms_key.secret", "aws_kms_key")]}]}}}
        retained, disposable = selection(state)
        self.assertEqual(disposable, ["aws_db_instance.gateway"])
        self.assertEqual(len(retained), 2)

    def test_rejects_retained_resource_added_by_dependency_graph(self):
        change = resource("aws_kms_key.storage", "aws_kms_key")
        change["change"] = {"actions": ["delete"]}
        with self.assertRaisesRegex(ValueError, "retained"):
            verify_plan({"resource_changes": [change]}, ["aws_db_instance.gateway"])

    def test_rejects_unselected_deletion_and_resource_replacement(self):
        change = resource("aws_db_instance.other", "aws_db_instance")
        for actions in (["delete"], ["delete", "create"]):
            change["change"] = {"actions": actions}
            with self.assertRaises(ValueError):
                verify_plan({"resource_changes": [change]}, ["aws_db_instance.gateway"])

    def test_accepts_selected_disposable_deletion(self):
        change = resource("aws_db_instance.gateway", "aws_db_instance")
        change["change"] = {"actions": ["delete"]}
        self.assertEqual(verify_plan({"resource_changes": [change]}, [change["address"]]), [change["address"]])
