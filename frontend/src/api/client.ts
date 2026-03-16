import axios from 'axios'
import { showToast } from '../components/common/Toast'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
})

client.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      window.location.href = '/login'
      return Promise.reject(error)
    }

    const data = error.response?.data
    if (data?.detail) {
      showToast(data.detail, 'error')
    } else if (!error.response) {
      showToast('서버에 연결할 수 없습니다', 'error')
    }

    return Promise.reject(error)
  },
)

export default client
