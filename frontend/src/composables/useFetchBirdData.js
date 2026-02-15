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

  const fetchChartsData = async (date) => {
    logger.info('Fetching charts data', { date });
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
            .get('/activity/overview', { params: { date } })
            .then(response => {
              logger.api('GET', '/activity/overview', { date }, response);
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

  const fetchDashboardData = async () => {
    logger.info('Fetching dashboard data');
    try {
      const today = new Date().toLocaleDateString("en-CA");
      fetchChartsData(today);

      const [
        latestObservationResponse,
        recentObservationsResponse,
        summaryResponse,
      ] = await Promise.all([
        api
          .get('/observations/latest')
          .then(response => {
            logger.api('GET', '/observations/latest', null, response);
            return response;
          })
          .catch((error) => {
            logger.error('Failed to fetch latest observation', error);
            return { error };
          }),
        api
          .get('/observations/recent')
          .then(response => {
            logger.api('GET', '/observations/recent', null, response);
            return response;
          })
          .catch((error) => {
            logger.error('Failed to fetch recent observations', error);
            return { error };
          }),
        api
          .get('/observations/summary')
          .then(response => {
            logger.api('GET', '/observations/summary', null, response);
            return response;
          })
          .catch((error) => {
            logger.error('Failed to fetch summary', error);
            return { error };
          }),
      ]);

      latestObservationData.value = latestObservationResponse.error
        ? null
        : latestObservationResponse.data;

      latestObservationError.value = latestObservationResponse.error
        ? "Hmm, cannot reach the server"
        : null;

      recentObservationsData.value = recentObservationsResponse.error
        ? []
        : recentObservationsResponse.data;

      recentObservationsError.value = recentObservationsResponse.error
        ? "Hmm, cannot reach the server"
        : null;

      summaryData.value = summaryResponse.error ? {} : summaryResponse.data;

      summaryError.value = summaryResponse.error
        ? "Hmm, cannot reach the server"
        : null;

      if (latestObservationData.value) {
        logger.debug('Fetching wikimedia image', { species: latestObservationData.value.common_name });
        const wikimediaImageResponse = await api.get(
          '/wikimedia_image',
          { params: { species: latestObservationData.value.common_name } }
        );
        logger.api('GET', '/wikimedia_image',
          { species: latestObservationData.value.common_name },
          wikimediaImageResponse);
        if (!wikimediaImageResponse.error) {
          if (wikimediaImageResponse.data.hasCustomImage) {
            latestObservationimageUrl.value =
              getBirdImageUrl(latestObservationData.value.common_name);
          } else {
            latestObservationimageUrl.value =
              wikimediaImageResponse.data.imageUrl;
          }
        }
      }
      
      logger.info('Dashboard data fetched successfully', {
        hasLatestObservation: !!latestObservationData.value,
        recentObservationsCount: recentObservationsData.value.length,
        hasSummary: !!summaryData.value
      });
    } catch (error) {
      logger.error('Error fetching dashboard data', error);
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
