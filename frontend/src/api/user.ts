/**
 * User API Module
 */

import axiosInstance from './axios';
import { User, Settings } from '../store/types';

export const userApi = {
  /**
   * Get current user profile
   */
  getProfile: async (): Promise<User> => {
    const response = await axiosInstance.get('/user/profile');
    return response.data;
  },

  /**
   * Update user profile
   */
  updateProfile: async (data: Partial<User>): Promise<User> => {
    const response = await axiosInstance.put('/user/profile', data);
    return response.data;
  },

  /**
   * Update user settings
   */
  updateSettings: async (settings: Partial<Settings>): Promise<Settings> => {
    const response = await axiosInstance.put('/user/settings', settings);
    return response.data;
  },
};
