from django.test import TransactionTestCase
from dashboard.models import Bot, BotReportData, CPUArchitecture, GPUType, Platform, Browser, Test, \
    MetricUnit
from rest_framework.test import APIClient
from collections import OrderedDict

client = APIClient()


class BotReportDataTestCase(TransactionTestCase):
    bot_id = "test_bot"
    bot_password = "test_pwd"
    test_version = "https://test.dummy.org/test_root_test/@r182170"
    browser_version = 'test_browser_version'

    def setUp(self):
        test_cpu_arch = CPUArchitecture.objects.create(name='test_cpu', enabled=True)
        test_gpu_type = GPUType.objects.create(name='test_gpu', enabled=True)
        test_platform = Platform.objects.create(name='test_platform', enabled=True)
        Bot.objects.create(
            password=self.bot_password, name=self.bot_id, cpuArchitecture=test_cpu_arch,
            cpuDetail='test_cpu_detail', gpuType=test_gpu_type, gpuDetail='test_gpu_detail',
            platform=test_platform, platformDetail='test_platform_detail', enabled=True
        )
        Browser.objects.create(id='test_browser', name='Test_Browser', enabled=True)
        Test.objects.create(
            id='test_root_test', description='test_root_test_desc', url='http://something_here.com',
            enabled=True
        )
        MetricUnit.objects.bulk_create([
            MetricUnit(
                name='Score', unit='pt', description='test_description_score', prefix=[{"unit": 1.0, "symbol": 'pt'}]
            ),
            MetricUnit(
                name='Time', unit='ms', description='test_description_time', prefix=[{"unit": 1.0, "symbol": 'ms'}]
            )
        ])

    def test_bot_authentications(self):
        """Test all possible authentication cases"""
        upload_data = OrderedDict([
            ('bot_id', self.bot_id+self.bot_id),('bot_password', self.bot_password), ('browser_id', 'test_browser'),
            ('browser_version', self.browser_version), ('test_id', 'test_root_test'),
            ('test_version', self.test_version),
            ('test_data', '{"test_root_test": {"metrics": {"Time": {"current": [1, 2, 3]},"Score": {"current": [2, 3, 4]}}}}')
        ])
        response = client.post('/dash/bot-report/', dict(upload_data))
        self.assertEqual(response.data['detail'], "This bot cannot be authenticated")

        # Try POSTing with wrong password, and cehck if the data went well
        upload_data = OrderedDict([
            ('bot_id', self.bot_id),('bot_password', self.bot_password+self.bot_password ), ('browser_id', 'test_browser'),
            ('browser_version', self.browser_version), ('test_id', 'test_root_test'),
            ('test_version', self.test_version),
            ('test_data', '{"test_root_test": {"metrics": {"Time": {"current": [1, 2, 3]},"Score": {"current": [2, 3, 4]}}}}')
        ])
        response = client.post('/dash/bot-report/', dict(upload_data))
        self.assertEqual(response.data['detail'],"Bad authentication details")
        self.assertEqual(BotReportData.objects.all().count(), 0)

    def test_data_no_aggregation_uploaded_correctly(self):
        # Try POSTing to the path, and cehck if the data went well
        upload_data = OrderedDict([
            ('bot_id', self.bot_id),('bot_password', self.bot_password), ('browser_id', 'test_browser'),
            ('browser_version', self.browser_version), ('test_id', 'test_root_test'),
            ('test_version', self.test_version),
            ('test_data', '{"test_root_test": {"metrics": {"Time": {"current": [1, 2, 3]},"Score": {"current": [2, 3, 4]}}}}')
        ])
        response = client.post('/dash/bot-report/', dict(upload_data))
        self.assertEqual(response.status_code, 200)

        # There should be two objects created
        self.assertEqual(BotReportData.objects.all().count(), 2)

        # Check for individual items
        score_object = BotReportData.objects.get(metric_unit='Score')
        time_object = BotReportData.objects.get(metric_unit='Time')

        self.assertEqual(score_object.mean_value, 3.0)
        self.assertEqual(round(score_object.stddev*100, 2), 33.33)
        self.assertEqual(time_object.mean_value, 2.0)
        self.assertEqual(round(time_object.stddev*100, 2), 50.00)

        self.assertEqual(score_object.prev_result, None)
        self.assertEqual(time_object.prev_result, None)
