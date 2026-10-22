import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// const API_BASE_URL = 'http://10.0.2.2:8000/api'; // Android Emulator
// const API_BASE_URL = 'http://192.0.0.2:8000/api';   // Hotspot network
// const API_BASE_URL = 'http://localhost:8000/api';   // Real Device (adb reverse)
const API_BASE_URL = 'https://api-riskpulse.delightfulglacier-38eeee86.koreacentral.azurecontainerapps.io/api';

const client = axios.create({
  baseURL: 'https://api-riskpulse.delightfulglacier-38eeee86.koreacentral.azurecontainerapps.io/api',
  timeout: 10000,
  headers: { 'Content-Type': 'application/json' },
});

// Share token rotation between REST retries and the long-lived camera connection.
let refreshInFlight: Promise<string> | null = null;
export function refreshAccessToken(): Promise<string> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      const refresh = await AsyncStorage.getItem('refresh_token');
      if (!refresh) throw new Error('로그인이 필요합니다.');
      const response = await axios.post(`${API_BASE_URL}/user/refresh/`, { refresh }, { timeout: 10000 });
      const tokens = response.data;
      if (!tokens.access) throw new Error('Access token missing');
      await AsyncStorage.setItem('access_token', tokens.access);
      if (tokens.refresh) await AsyncStorage.setItem('refresh_token', tokens.refresh);
      return tokens.access as string;
    })().finally(() => { refreshInFlight = null; });
  }
  return refreshInFlight;
}

// 요청 인터셉터: 매 요청마다 access 토큰 헤더에 추가
client.interceptors.request.use(async config => {
  const token = await AsyncStorage.getItem('access_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 응답 인터셉터: 403 시 refresh 토큰으로 재발급 후 재시도
client.interceptors.response.use(
  response => response,
  async error => {
    const originalRequest = error.config;

    const status = error.response?.status;
    if ((status === 401 || status === 403) && !originalRequest._retry) {
      originalRequest._retry = true;

      const refreshToken = await AsyncStorage.getItem('refresh_token');
      if (!refreshToken) {
        return Promise.reject(error);
      }

      try {
        const access = await refreshAccessToken();

        originalRequest.headers.Authorization = `Bearer ${access}`;
        return client(originalRequest);
      } catch {
        // refresh 실패 시 토큰 삭제
        await AsyncStorage.multiRemove(['access_token', 'refresh_token']);
        return Promise.reject(error);
      }
    }

    return Promise.reject(error);
  },
);

export default client;
