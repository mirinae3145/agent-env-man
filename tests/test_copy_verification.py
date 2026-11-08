"""Copy diagnostics distinguish changing sources from invalid staged copies."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from agent_env_man.storage import copy_payload, fingerprint, observation
import test_directories as directory_tests


class CopyVerification(unittest.TestCase):
    def check_failure(self, *, change_source=False, change_mode=False):
        for detach in (False, True):
            for preserve in (False, True):
                with self.subTest(detach=detach, preserve_symlinks=preserve):
                    case = directory_tests.Directories()
                    try:
                        case.setUp()
                        if detach:
                            case.require_links()
                        case.document['directories']['cases']['preserve_symlinks'] = preserve
                        case.external(mode='link' if detach else 'copy')
                        case.run_cli('apply', '--item', 'cases')
                        source = case.external_root
                        if not detach:
                            (source / 'first.md').write_text('incoming content', encoding='utf-8')
                        expected_source = fingerprint(source, preserve_symlinks=preserve)
                        expected_target = observation(case.target, preserve_symlinks=preserve)
                        expected_records = deepcopy(case.manager().state.data['items'])

                        def altered_copy(source, destination, **policy):
                            copy_payload(source, destination, **policy)
                            if change_source:
                                (source / 'first.md').write_text('concurrent source edit', encoding='utf-8')
                            if change_mode:
                                file = destination / 'first.md'
                                file.chmod((file.stat().st_mode & 0o777) ^ 0o100)
                            else:
                                (destination / 'first.md').write_text('damaged staged copy', encoding='utf-8')

                        with patch('agent_env_man.manager.copy_payload', side_effect=altered_copy):
                            error = (case.run_cli('detach', 'cases', code=1) if detach
                                     else case.run_cli('apply', '--item', 'cases', code=1))
                        if change_source:
                            self.assertIn('linked contents changed during detach' if detach
                                          else 'source changed while copying', error)
                        else:
                            self.assertIn('materialized copy differs from linked contents' if detach
                                          else 'copied payload differs from source', error)
                            self.assertIn('executable permissions', error)
                            self.assertEqual(fingerprint(source, preserve_symlinks=preserve), expected_source)
                        self.assertEqual(observation(case.target, preserve_symlinks=preserve), expected_target)
                        state = case.manager().state.data
                        self.assertEqual(state['items'], expected_records)
                        self.assertIsNone(state['pending'])
                        self.assertFalse(list(case.target.parent.glob('.aem-stage-*')))
                        self.assertFalse(list(case.target.parent.glob('*.aem-backup-*')))
                    finally:
                        case.doCleanups()

    def test_staged_content_mismatch_preserves_installation(self):
        self.check_failure()

    def test_staged_permission_mismatch_preserves_installation(self):
        self.check_failure(change_mode=True)

    def test_concurrent_source_change_takes_priority_over_staged_mismatch(self):
        self.check_failure(change_source=True)
