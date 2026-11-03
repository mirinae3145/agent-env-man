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

    def test_default_baselines_use_newest_final_and_newest_release(self):
        select = self.verifier['default_baselines']
        tags = ['v1.2.0', 'v1.2.0-rc.3', 'v1.2.1', 'v1.3.0-beta.1', 'v1.3.0-beta.2', 'archive-pr25', 'v1.10.0a1']
        self.assertEqual(select(tags), ['v1.2.1', 'v1.10.0a1'])
        self.assertEqual(select(['v1.2.0', 'v1.2.1']), ['v1.2.1'])
        self.assertEqual(select(['v1.0.0-rc.1']), ['v1.0.0-rc.1'])
        self.assertEqual(select(['other']), [])

    def test_differences_name_changed_paths(self):
        differences = self.verifier['differences']
        self.assertEqual(differences({'a': [1, {'b': 2}]}, {'a': [1, {'b': 2}]}), [])
        self.assertEqual(differences({'a': [1, {'b': 2}], 'c': 1}, {'a': [1, {'b': 3}]}),
                         ['$.a[1].b: 2 -> 3', '$.c: 1 -> None'])


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
