/**
 * Authentication API Module
 */

import axiosInstance from './axios';
import { User, AuthResponse } from '../store/types';

export const authApi = {
  /**
   * Login with email and password
   */
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const response = await axiosInstance.post('/auth/login', {
      email,
      password,
    });
    return response.data;
  },

  /**
   * Register a new user
   */
  register: async (
    fullName: string,
    email: string,
    password: string
  ): Promise<AuthResponse> => {
    const response = await axiosInstance.post('/auth/register', {
      full_name: fullName,
      email,
      password,
    });
    return response.data;
  },

  /**
   * Logout current user
   */
  logout: async (): Promise<void> => {
    await axiosInstance.post('/auth/logout');
  },

  /**
   * Refresh access token
   */
  refreshToken: async (refreshToken: string): Promise<{ access_token: string }> => {
    const response = await axiosInstance.post('/auth/refresh', {
      refresh_token: refreshToken,
    });
    return response.data;
  },

  /**
   * Get current user profile
   */
  getProfile: async (): Promise<User> => {
    const response = await axiosInstance.get('/auth/profile');
    return response.data;
  },
};
