import allure


tabs = (
    'dashboard', 'incidents', 'activehosts', 'deception-accounts', 'deception-targets',
    'credential-defender-rules', 'credential-defender-infringement', 'policies',
    'decoys-trap-servers', 'decoys-decoys', 'decoys-mitm', 'settings-infrastructure',
    'settings-users', 'settings-integration', 'settings-slave-servers', 'settings-exclusion',
    'settings-roles', 'settings-license', 'settings-deploy', 'settings-common'
)

for tab in tabs:
    def make_test(tab_name):
        @allure.feature('API Tests')
        @allure.story('Audit')
        @allure.title(f'Audit test for "{tab_name}"')
        def test_audit(session):
            with allure.step(f'Проверка запроса аудита на вкладке "{tab_name}"'):
                response = session.post('management/settings/audit', json={'tabName': tab_name})
                assert response.status_code == 200, f"Ожидали 200, получили {response.status_code}"

        return test_audit

    globals()[f'test_audit_{tab}'] = make_test(tab)
