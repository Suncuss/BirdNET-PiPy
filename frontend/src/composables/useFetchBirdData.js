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

  // Cached activity overview for both orders (instant toggle)
  let activityOverviewCache = { most: [], least: [] };

  const setActivityOrder = (order) => {
    detailedBirdActivityData.value = activityOverviewCache[order] || [];
  };

  const fetchDashboardData = async () => {
    logger.info('Fetching dashboard data');
    try {
      const response = await api.get('/dashboard');
      logger.api('GET', '/dashboard', null, response);

      const data = response.data;
      const previousSpecies = latestObservationData.value?.common_name;
      const newSpecies = data.latestObservation?.common_name;

      latestObservationData.value = data.latestObservation;
      latestObservationError.value = null;

      recentObservationsData.value = data.recentObservations;
      recentObservationsError.value = null;

      summaryData.value = data.summary;
      summaryError.value = null;

      hourlyBirdActivityData.value = data.hourlyActivity;
      hourlyBirdActivityError.value = null;

      activityOverviewCache = data.activityOverview;
      detailedBirdActivityError.value = null;

      if (newSpecies && newSpecies !== previousSpecies) {
        latestObservationimageUrl.value = '/default_bird.webp';
        logger.debug('Fetching wikimedia image', { species: newSpecies });
        api.get('/wikimedia_image', { params: { species: newSpecies } })
          .then(wikimediaImageResponse => {
            if (latestObservationData.value?.common_name !== newSpecies) return;
            logger.api('GET', '/wikimedia_image', { species: newSpecies }, wikimediaImageResponse);
            if (wikimediaImageResponse.data.hasCustomImage) {
              latestObservationimageUrl.value = getBirdImageUrl(newSpecies);
            } else {
              latestObservationimageUrl.value =
                wikimediaImageResponse.data.imageUrl;
            }
          })
          .catch(imageError => {
            logger.error('Failed to fetch wikimedia image', imageError);
          });
      } else if (!newSpecies) {
        latestObservationimageUrl.value = '/default_bird.webp';
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
      activityOverviewCache = { most: [], least: [] };
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
    setActivityOrder,
    fetchChartsData,
    fetchTrendsData,
  };
}
