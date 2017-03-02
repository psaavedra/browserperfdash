from django.shortcuts import render
from django.shortcuts import redirect
from django.views.generic import TemplateView
from django.http import Http404
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import authentication, permissions
from rest_framework import generics
from dashboard.models import *
from rest_framework import exceptions
import json
from helpers.benchmark_results import BenchmarkResults
from django.views.generic import ListView, DetailView
from .serializers import *
import datetime

import logging

log = logging.getLogger(__name__)


class BotAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        bot_name = request.POST.get('bot_id')
        bot_password = request.POST.get('bot_password')

        if not bot_name or not bot_password:
            return None

        try:
            bot = Bot.objects.get(name=bot_name)
            if bot.password != bot_password:
                raise exceptions.AuthenticationFailed('Bad authentication details')
        except Bot.DoesNotExist:
            raise exceptions.AuthenticationFailed('This bot cannot be authenticated')

        return (bot, bot_name)


class BotDataReportListView(generics.ListCreateAPIView):
    model = BotReportData
    queryset = BotReportData.objects.filter(aggregation='None')
    serializer_class = BotReportDataSerializer


class BotDataCompleteListView(generics.ListCreateAPIView):
    model = BotReportData
    queryset = BotReportData.objects.filter()
    serializer_class = BotDataCompleteSerializer


class BotDataReportDetailView(generics.RetrieveAPIView):
    model = BotReportData
    queryset = BotReportData.objects.filter(aggregation='None')
    serializer_class = BotReportDataSerializer


class BotResultsForTestListView(generics.ListAPIView):
    model = BotReportData
    queryset = BotReportData.objects.filter(aggregation='None')
    serializer_class = BotReportDataSerializer

    def get_queryset(self):
        obj = BotReportData.objects.get(pk=self.kwargs.get('pk'))
        queryset = super(BotResultsForTestListView, self).get_queryset()
        return queryset.filter(browser=obj.browser, root_test=obj.root_test, test_path=obj.test_path,
                               aggregation=obj.aggregation, bot=obj.bot)


class BrowsersList(generics.ListAPIView):
    model = Browser
    queryset = Browser.objects.filter(enabled=True)
    serializer_class = BrowserListSerializer


class BotsList(generics.ListAPIView):
    model = Bot
    queryset = Bot.objects.filter(enabled=True)
    serializer_class = BotListSerializer


class PlatformList(generics.ListAPIView):
    model = Platform
    queryset = Platform.objects.filter(enabled=True)
    serializer_class = PlatformListSerializer


class GPUTypeList(generics.ListAPIView):
    model = GPUType
    queryset = GPUType.objects.filter(enabled=True)
    serializer_class = GPUTypeListSerializer


class CPUArchitectureList(generics.ListAPIView):
    model = CPUArchitecture
    queryset = CPUArchitecture.objects.filter(enabled=True)
    serializer_class = CPUArchitectureListSerializer


class TestList(generics.ListAPIView):
    model = Test
    queryset = Test.objects.filter(enabled=True)
    serializer_class = TestListListSerializer


class TestPathList(generics.ListAPIView):
    serializer_class = TestPathListSerializer

    def get_queryset(self):
        browser = Browser.objects.filter(pk=self.kwargs.get('browser'))
        test = Test.objects.filter(pk=self.kwargs.get('test'))
        return BotReportData.objects.filter(browser=browser, root_test=test)


class TestVersionForTestPathList(generics.ListAPIView):
    serializer_class = TestVersionForTestPathListSerializer

    def get_queryset(self):
        browser = Browser.objects.filter(pk=self.kwargs.get('browser'))
        test = Test.objects.filter(pk=self.kwargs.get('test'))
        test_path = self.kwargs.get('subtest')
        return BotReportData.objects.filter(browser=browser, root_test=test, test_path=test_path)


class DefaultHomeView(ListView):
    template_name="index.html"

    def get_queryset(self):
        return BotReportData.objects.all()


class BotDataReportList(TemplateView):
    template_name="allresults.html"


class BotDataReportDetail(TemplateView):
    template_name = "report.html"


class GraphPlotView(TemplateView):
    template_name = "plot.html"


class BotReportView(APIView):
    authentication_classes = (BotAuthentication,)
    permission_classes = (permissions.IsAuthenticatedOrReadOnly,)

    @classmethod
    def is_aggregated(cls, metric):
        return not metric.endswith(":None")

    @classmethod
    def extract_metric(cls, metric):
        return metric.split(':')[0]

    @classmethod
    def extract_aggregation(cls, metric):
        return metric.split(':')[1]

    @classmethod
    def process_delta_and_improvement(cls, browser, root_test, test_path, mean_value, current_metric):
        delta = 0.0
        # We take in the previous result (if exists)
        previous_result = BotReportData.objects.filter(browser=browser, root_test=root_test, test_path=test_path
                                                       ).order_by('-timestamp')[:1]

        is_improvement = False
        prev_result = None
        if previous_result:
            for res in previous_result:
                prev_result = res
                delta = abs(1-float(res.mean_value)/float(mean_value))*100.00
                if current_metric.is_better == 'up':
                    if float(res.mean_value) < float(mean_value):
                        is_improvement = True
                elif current_metric.is_better == 'dw':
                    if float(res.mean_value) > float(mean_value):
                        is_improvement = True

        return [delta, is_improvement, prev_result]

    def post(self, request, format=None):
        try:
            browser_id = self.request.POST.get('browser_id')
            browser_version = self.request.POST.get('browser_version')
            test_id = self.request.POST.get('test_id')
            test_version = self.request.POST.get('test_version')
            bot_id = self.request.POST.get('bot_id')
            json_data = self.request.POST.get('test_data')
        except AttributeError:
            log.error("Got invalid params from the bot: %s"% request.auth)
            return HttpResponseBadRequest("Some params are missing in the request")
        # The timestamp may/may not be there - hence not checking
        timestamp = datetime.datetime.fromtimestamp(float(self.request.POST.get('timestamp'))) \
            if self.request.POST.get('timestamp') else None
        try:
            test_data = json.loads(json_data)
        except AttributeError:
            return HttpResponseBadRequest("Error parsing JSON file from bot: %s "% request.auth)

        bot = Bot.objects.get(pk=bot_id)

        if not bot.enabled:
            log.error("Got data from disabled bot: %s" % (bot_id))
            return HttpResponseBadRequest("The bot %s is not enabled"% bot_id)

        try:
            browser = Browser.objects.get(pk=browser_id)
        except Browser.DoesNotExist:
            log.error("Got invalid browser %s from bot: %s" % (browser_id, bot_id))
            return HttpResponseBadRequest("The browser does not exist")
        try:
            root_test = Test.objects.get(pk__iexact=test_id)
        except Test.DoesNotExist:
            log.error("Got invalid root test: %s from bot: %s for browser: %s, browser_version: %s" %
                      (test_id, bot_id, browser_id, browser_version))
            return HttpResponseBadRequest("The test %s does not exist"% test_id )

        test_data_results = BenchmarkResults(test_data)
        results_table = test_data_results.fetch_db_entries(skip_aggregated=False)

        for result in results_table:
            raw_path = result['name']

            metric_name = self.extract_metric(result['metric'])
            stddev = float(result['stdev'])
            mean_value = float(result['value'])
            unit = result['unit']

            try:
                current_metric = MetricUnit.objects.get(pk=metric_name)
            except MetricUnit.DoesNotExist:
                log.error("Got wrong Metric %s for bot: %s, browser: %s, browser_version: %s, root_test: %s,"
                          " test_description: %s" % (metric_name, bot_id, browser_id, browser_version, test_id, raw_path)
                          )
                return HttpResponseBadRequest("The Metric Unit %s does not exist"% metric_name)

            if current_metric.unit != unit:
                log.error("Got wrong unit %s for metric unit %s data for bot: %s, browser: %s, browser_version: %s, "
                          "root_test: %s, test_description: %s" % (unit, metric_name, bot_id, browser_id, browser_version,
                                                                   test_id, raw_path)
                          )
                return HttpResponseBadRequest("The received unit: %s field of Metric Unit %s does not match" % (unit,metric_name))

            if self.is_aggregated(metric=result['metric']):
                aggregation = self.extract_aggregation(metric=result['metric'])
            else:
                aggregation = 'None'

            # Calculate the change and store it during processing the POST
            delta_improvements = self.process_delta_and_improvement(browser, root_test, raw_path, mean_value, current_metric)
            delta = delta_improvements[0]
            is_improvement = delta_improvements[1]
            prev_result = delta_improvements[2]

            report = BotReportData.objects.create_report(bot=bot, browser=browser, browser_version=browser_version,
                                                         root_test=root_test, test_path=raw_path,
                                                         test_version=test_version, aggregation=aggregation,
                                                         metric_tested= current_metric, mean_value=mean_value,
                                                         stddev=stddev,delta=delta,is_improvement=is_improvement,
                                                         prev_result=prev_result, timestamp=timestamp)
            if not report:
                log.error("Failed inserting data for bot: %s, browser: %s, browser_version: %s, root_test: %s, "
                          "test_description: %s" % (bot_id, browser_id, browser_version, test_id,raw_path)
                          )

        return HttpResponse("The POST went through")