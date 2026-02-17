import { ref } from "vue";
import api from "@/services/api";
import { getBirdImageUrl } from "@/services/media";
import { useLogger } from "./useLogger";

export function useFetchBirdData() {
  const logger = useLogger('useFetchBirdData');
  const detailedBirdActivityData = ref([]);
  const hourlyBirdActivityData = ref([]);

  const latestObservationData = ref(null);
  const recentObservationsData = ref([]);
  const summaryData = ref({});

  const detailedBirdActivityError = ref(null);
  const hourlyBirdActivityError = ref(null);

  const latestObservationError = ref(null);
  const recentObservationsError = ref(null);
  const summaryError = ref(null);

  const trendsData = ref({ labels: [], data: [] });
  const trendsError = ref(null);

  const latestObservationimageUrl = ref("/default_bird.webp");

  const fetchChartsData = async (date, order = 'most') => {
    logger.info('Fetching charts data', { date, order });
    try {
      const [hourlyBirdActivityResponse, detailedBirdActivityResponse] =
        await Promise.all([
          api
            .get('/activity/hourly', { params: { date } })
            .then(response => {
              logger.api('GET', '/activity/hourly', { date }, response);
              return response;
            })
            .catch((error) => {
              logger.error('Failed to fetch hourly activity', error);
              return { error };
            }),
          api
            .get('/activity/overview', { params: { date, order } })
            .then(response => {
              logger.api('GET', '/activity/overview', { date, order }, response);
              return response;
            })
            .catch((error) => {
              logger.error('Failed to fetch activity overview', error);
              return { error };
            }),
        ]);

      hourlyBirdActivityData.value = hourlyBirdActivityResponse.error
        ? []
        : hourlyBirdActivityResponse.data;

      hourlyBirdActivityError.value = hourlyBirdActivityResponse.error
        ? "Hmm, cannot reach the server"
        : null;

      detailedBirdActivityData.value = detailedBirdActivityResponse.error
        ? []
        : detailedBirdActivityResponse.data;

      detailedBirdActivityError.value = detailedBirdActivityResponse.error
        ? "Hmm, cannot reach the server"
        : null;
      
      logger.debug('Charts data fetched successfully', {
        hourlyDataCount: hourlyBirdActivityData.value.length,
        detailedDataCount: detailedBirdActivityData.value.length
      });
    } catch (error) {
      logger.error('Error fetching charts data', error);
    }
  };

  const fetchDashboardData = async (order = 'most') => {
    logger.info('Fetching dashboard data', { order });
    try {
      const response = await api.get('/dashboard', { params: { order } });
      logger.api('GET', '/dashboard', { order }, response);

      const data = response.data;

      latestObservationData.value = data.latestObservation;
      latestObservationError.value = null;

      recentObservationsData.value = data.recentObservations;
      recentObservationsError.value = null;

      summaryData.value = data.summary;
      summaryError.value = null;

      hourlyBirdActivityData.value = data.hourlyActivity;
      hourlyBirdActivityError.value = null;

      detailedBirdActivityData.value = data.activityOverview;
      detailedBirdActivityError.value = null;

      latestObservationimageUrl.value = '/default_bird.webp';

      if (latestObservationData.value) {
        const species = latestObservationData.value.common_name;
        logger.debug('Fetching wikimedia image', { species });
        api.get('/wikimedia_image', { params: { species } })
          .then(wikimediaImageResponse => {
            if (latestObservationData.value?.common_name !== species) return;
            logger.api('GET', '/wikimedia_image', { species }, wikimediaImageResponse);
            if (wikimediaImageResponse.data.hasCustomImage) {
              latestObservationimageUrl.value = getBirdImageUrl(species);
            } else {
              latestObservationimageUrl.value =
                wikimediaImageResponse.data.imageUrl;
            }
          })
          .catch(imageError => {
            logger.error('Failed to fetch wikimedia image', imageError);
          });
      }

      logger.info('Dashboard data fetched successfully', {
        hasLatestObservation: !!latestObservationData.value,
        recentObservationsCount: recentObservationsData.value.length,
        hasSummary: !!summaryData.value
      });
    } catch (error) {
      logger.error('Error fetching dashboard data', error);

      const errMsg = 'Hmm, cannot reach the server';
      latestObservationData.value = null;
      latestObservationError.value = errMsg;
      recentObservationsData.value = [];
      recentObservationsError.value = errMsg;
      summaryData.value = {};
      summaryError.value = errMsg;
      hourlyBirdActivityData.value = [];
      hourlyBirdActivityError.value = errMsg;
      detailedBirdActivityData.value = [];
      detailedBirdActivityError.value = errMsg;
    }
  };

  const fetchTrendsData = async (startDate, endDate) => {
    logger.info('Fetching trends data', { startDate, endDate });
    trendsError.value = null;

    try {
      const response = await api.get('/detections/trends', {
        params: { start_date: startDate, end_date: endDate }
      });
      logger.api('GET', '/detections/trends', { startDate, endDate }, response);

      trendsData.value = response.data;

      logger.debug('Trends data fetched successfully', {
        days: trendsData.value.labels?.length || 0,
        totalDetections: trendsData.value.data?.reduce((a, b) => a + b, 0) || 0
      });

      return response.data;
    } catch (error) {
      logger.error('Failed to fetch trends data', error);
      trendsError.value = 'Hmm, cannot reach the server';
      trendsData.value = { labels: [], data: [] };
      return null;
    }
  };

  return {
    hourlyBirdActivityData,
    detailedBirdActivityData,
    latestObservationData,
    recentObservationsData,
    summaryData,
    hourlyBirdActivityError,
    detailedBirdActivityError,
    latestObservationError,
    recentObservationsError,
    summaryError,
    trendsData,
    trendsError,
    latestObservationimageUrl,
    fetchDashboardData,
    fetchChartsData,
    fetchTrendsData,
  };
}
