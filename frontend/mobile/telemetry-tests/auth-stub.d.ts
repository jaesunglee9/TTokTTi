declare module '@react-native-async-storage/async-storage' {
  const storage: { getItem(key: string): Promise<string | null>; setItem(key: string, value: string): Promise<void>; multiRemove(keys: string[]): Promise<void> };
  export default storage;
}
declare module 'axios' {
  interface Client {
    interceptors: {
      request: { use(callback: (config: any) => any): void };
      response: { use(success: (response: any) => any, error: (error: any) => any): void };
    };
    (config: any): Promise<any>;
  }
  const axios: { create(config: any): Client; post(url: string, body: any, config?: any): Promise<any> };
  export default axios;
}
