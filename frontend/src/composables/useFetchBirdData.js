import { ref } from "vue";
import api from "@/services/api";
import { getBirdImageUrl, getDefaultBirdImageUrl, isDefaultBirdImageUrl } from "@/services/media";
import { ERR_UNREACHABLE } from "@/utils/errorMessages";
import { useLogger } from "./useLogger";

export function useFetchBirdData() {
  const logger = useLogger('useFetchBirdData');
  const detailedBirdActivityData = ref([]);
  const hourlyBirdActivityData = ref([]);

  const latestObservationData = ref(null);
  const recentObservationsData = ref([]);
  const summaryData = ref({});
  const summaryLoading = ref({});
  const summaryErrors = ref({});

  const detailedBirdActivityError = ref(null);
  const hourlyBirdActivityError = ref(null);

  const latestObservationError = ref(null);
  const recentObservationsError = ref(null);
  const summaryError = ref(null);

  const trendsData = ref({ labels: [], data: [] });
  const trendsError = ref(null);

  const hasLoadedOnce = ref(false);

  const latestObservationimageUrl = ref(getDefaultBirdImageUrl());

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
        ? ERR_UNREACHABLE
        : null;

      detailedBirdActivityData.value = detailedBirdActivityResponse.error
        ? []
        : detailedBirdActivityResponse.data;

      detailedBirdActivityError.value = detailedBirdActivityResponse.error
        ? ERR_UNREACHABLE
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

  // Cached recent observations for both modes (instant toggle)
  let recentObservationsCache = { all: [], unique: [] };
  let currentActivityOrder = 'most';
  let currentRecentObsMode = 'all';

  const setSummaryLoading = (period, loading) => {
    summaryLoading.value = { ...summaryLoading.value, [period]: loading };
  };

  const setSummaryError = (period, error) => {
    summaryErrors.value = { ...summaryErrors.value, [period]: error };
  };

  const applyDashboardSelections = () => {
    recentObservationsData.value = recentObservationsCache[currentRecentObsMode] || [];
    detailedBirdActivityData.value = activityOverviewCache[currentActivityOrder] || [];
  };

  const setRecentObsMode = (mode) => {
    currentRecentObsMode = mode;
    applyDashboardSelections();
  };

  const setActivityOrder = (order) => {
    currentActivityOrder = order;
    applyDashboardSelections();
  };

  // Fix 3: Fetch race guard — prevents stale responses from overwriting newer state
  let fetchVersion = 0;

  const fetchDashboardData = async (
    order = currentActivityOrder,
    { recentMode = currentRecentObsMode } = {}
  ) => {
    currentActivityOrder = order;
    currentRecentObsMode = recentMode;
    const myVersion = ++fetchVersion;
    logger.info('Fetching dashboard data');
    try {
      // /dashboard is a heavy aggregation — allow generous time on slow devices.
      const response = await api.get('/dashboard', { timeout: 45000 });

      // Bail out if a newer fetch has started while we were awaiting
      if (myVersion !== fetchVersion) return;

      logger.api('GET', '/dashboard', null, response);

      const data = response.data;
      const previousSpecies = latestObservationData.value?.common_name;
      const newSpecies = data.latestObservation?.common_name;

      latestObservationData.value = data.latestObservation;
      latestObservationError.value = null;

      recentObservationsCache = data.recentObservations || { all: [], unique: [] };
      recentObservationsError.value = null;

      summaryData.value = data.summary || {};
      Object.keys(data.summary || {}).forEach((period) => {
        setSummaryLoading(period, false);
      });
      // Server is reachable — drop stale per-period errors, including for
      // lazily-loaded periods absent from this payload.
      summaryErrors.value = {};
      summaryError.value = null;

      hourlyBirdActivityData.value = data.hourlyActivity;
      hourlyBirdActivityError.value = null;

      activityOverviewCache = data.activityOverview || { most: [], least: [] };
      applyDashboardSelections();
      detailedBirdActivityError.value = null;

      // Fix 4: Retry wikimedia image when still on default (e.g. previous fetch failed)
      const speciesChanged = newSpecies !== previousSpecies;
      const imageIsDefault = isDefaultBirdImageUrl(latestObservationimageUrl.value);
      if (newSpecies && (speciesChanged || imageIsDefault)) {
        if (speciesChanged) {
          latestObservationimageUrl.value = getDefaultBirdImageUrl();
        }
        logger.debug('Fetching wikimedia image', { species: newSpecies });
        api.get('/wikimedia_image', { params: { species: newSpecies } })
          .then(wikimediaImageResponse => {
            if (latestObservationData.value?.common_name !== newSpecies) return;
            logger.api('GET', '/wikimedia_image', { species: newSpecies }, wikimediaImageResponse);
            if (wikimediaImageResponse.data.hasCustomImage) {
              latestObservationimageUrl.value = getBirdImageUrl(newSpecies);
            } else {
              latestObservationimageUrl.value =
                isDefaultBirdImageUrl(wikimediaImageResponse.data.imageUrl)
                  ? getDefaultBirdImageUrl()
                  : wikimediaImageResponse.data.imageUrl;
            }
          })
          .catch(imageError => {
            logger.error('Failed to fetch wikimedia image', imageError);
          });
      } else if (!newSpecies) {
        latestObservationimageUrl.value = getDefaultBirdImageUrl();
      }

      hasLoadedOnce.value = true;

      logger.info('Dashboard data fetched successfully', {
        hasLatestObservation: !!latestObservationData.value,
        recentObservationsCount: recentObservationsData.value.length,
        hasSummary: !!summaryData.value
      });
    } catch (error) {
      // Bail out if a newer fetch has started
      if (myVersion !== fetchVersion) return;

      logger.error('Error fetching dashboard data', error);

      // A failed *refresh* must never destroy a good render — keep the last
      // data on screen and let the next poll retry. Only surface the error
      // when there is nothing to show yet (the very first load failed).
      if (!hasLoadedOnce.value) {
        latestObservationError.value = ERR_UNREACHABLE;
        recentObservationsError.value = ERR_UNREACHABLE;
        summaryError.value = ERR_UNREACHABLE;
        hourlyBirdActivityError.value = ERR_UNREACHABLE;
        detailedBirdActivityError.value = ERR_UNREACHABLE;
        hasLoadedOnce.value = true;
      }
    }
  };

  const fetchSummaryData = async (period, { force = false } = {}) => {
    if (!force && summaryData.value[period]) {
      return summaryData.value[period];
    }
    if (summaryLoading.value[period]) {
      return null;
    }

    // Spinner only on first load; a forced refresh keeps stale data visible.
    const showLoading = !summaryData.value[period];
    if (showLoading) {
      setSummaryLoading(period, true);
    }
    setSummaryError(period, null);
    summaryError.value = null;

    try {
      const response = await api.get('/dashboard/summary', {
        params: { period }
      });
      logger.api('GET', '/dashboard/summary', { period }, response);

      summaryData.value = {
        ...summaryData.value,
        [period]: response.data
      };
      return response.data;
    } catch (error) {
      logger.error('Failed to fetch summary data', error);
      setSummaryError(period, ERR_UNREACHABLE);
      return null;
    } finally {
      if (showLoading) {
        setSummaryLoading(period, false);
      }
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
      trendsError.value = ERR_UNREACHABLE;
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
    summaryLoading,
    summaryErrors,
    trendsData,
    trendsError,
    latestObservationimageUrl,
    hasLoadedOnce,
    fetchDashboardData,
    fetchSummaryData,
    setActivityOrder,
    setRecentObsMode,
    fetchChartsData,
    fetchTrendsData,
  };
}
