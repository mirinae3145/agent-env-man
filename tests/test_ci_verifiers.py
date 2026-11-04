"""End-to-end CI verifiers select releases and read agent output as intended."""

from pathlib import Path
import runpy
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'


class UpgradeVerifier(unittest.TestCase):
    def setUp(self):
        self.verifier = runpy.run_path(str(SCRIPTS / 'verify_upgrade.py'))

    def test_synthetic_release_orders_directly_after_candidate(self):
        next_release = self.verifier['next_release']
        self.assertEqual(next_release('1.3.0b2'), '1.3.0b3')
        self.assertEqual(next_release('1.3.0rc'), '1.3.0rc1')
        self.assertEqual(next_release('1.2.1'), '1.2.2')
        with self.assertRaises(RuntimeError):
            next_release('1.2.1.dev0')

    def test_default_baselines_cover_minor_and_current_prerelease_boundaries(self):
        select = self.verifier['default_baselines']
        tags = ['v0.5.3', 'v1.0.0', 'v1.0.1', 'v1.0.2', 'v1.1.0', 'v1.2.0', 'v1.2.0-rc.3',
                'v1.2.1', 'v1.3.0-beta.1', 'v1.3.0b1', 'v1.3.0-beta.2', 'v1.3.0-beta.3',
                'v1.3.0-rc.1', 'archive-pr25', 'v1.10.0a1', 'v2.0.0']
        self.assertEqual(select(tags, '1.3.0b3'),
                         ['v1.0.0', 'v1.0.2', 'v1.1.0', 'v1.2.0', 'v1.2.1',
                          'v1.3.0-beta.1', 'v1.3.0-beta.3'])
        self.assertEqual(select(['v1.2.0', 'v1.2.1'], '1.2.1'), ['v1.2.0', 'v1.2.1'])
        self.assertEqual(select(['v1.0.0-rc.1'], '1.0.0rc1'), ['v1.0.0-rc.1'])
        self.assertEqual(select(['other'], '1.3.0b3'), [])

    def test_compatible_upgrade_expectations(self):
        compatible = self.verifier['compatible_transition']
        for before, after, expected in [('1.0.0', '1.2.1', True), ('1.2.1', '1.3.0b4', False),
                                        ('1.3.0b1', '1.3.0b4', True), ('1.3.0b3', '1.3.0rc1', False),
                                        ('1.3.0b3', '1.3.0', False), ('1.3.0b3', '1.4.0b4', False),
                                        ('1.2.1', '2.0.0', False), ('0.2.0', '0.2.1', True),
                                        ('0.2.0', '0.3.0', False), ('1.2.1', '1.2.1', False)]:
            with self.subTest(before=before, after=after):
                self.assertEqual(compatible(before, after), expected)

    def test_differences_name_changed_paths(self):
        differences = self.verifier['differences']
        self.assertEqual(differences({'a': [1, {'b': 2}]}, {'a': [1, {'b': 2}]}), [])
        self.assertEqual(differences({'a': [1, {'b': 2}], 'c': 1}, {'a': [1, {'b': 3}]}),
                         ['$.a[1].b: 2 -> 3', '$.c: missing field'])

    def test_status_output_allows_additions_but_preserves_existing_fields(self):
        differences = self.verifier['differences']
        self.assertEqual(differences({'items': [{'name': 'old'}]},
                                     {'items': [{'name': 'old', 'kind': 'skill'}], 'new': True},
                                     allow_additions=True), [])
        self.assertEqual(differences({'value': None}, {}, allow_additions=True), ['$.value: missing field'])
        self.assertEqual(differences({'value': 1}, {'value': 2}, allow_additions=True), ['$.value: 1 -> 2'])


class AgentVerifier(unittest.TestCase):
    def test_skill_roots_expand_codex_aliases(self):
        listed = runpy.run_path(str(SCRIPTS / 'verify_agents.py'))['listed_skill_roots']
        prompt = ('### Skill roots\\n- `r0` = `/home/user/.agents/skills`\\n- `r1` = `/opt/skills`\\n'
                  '- idk-aem: Use AEM. (file: r0/idk-aem/SKILL.md)\\n'
                  '- other: Other. (file: r1/other/SKILL.md)\\n'
                  '- idk-aem: Copy. (file: /absolute/idk-aem/SKILL.md)\\n')
        self.assertEqual(listed(prompt, 'idk-aem'), {Path('/home/user/.agents/skills'), Path('/absolute')})
        self.assertEqual(listed(prompt, 'missing'), set())


if __name__ == '__main__':
    unittest.main()
