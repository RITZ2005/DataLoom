let baseURL: string = "";
let cdnBaseURL: string = "";
let appCode: string = "";
let region: string = "";
let version: string = "";
let bucketConfigurations: { bucketName: string, bucketId: string, clientId: string, purposeId: string, isPrivateBucket: boolean }[] = []

export const MQLOptions = {
  get version(): string {
    return version;
  },
  get region(): string {
    return region;
  },
  get appCode(): string {
    return appCode;
  },
  get baseURL(): string {
    return baseURL;
  },
  get cdnBaseURL(): string {
    return cdnBaseURL;
  },
  get cdnConfig(): { bucketName: string, bucketId: string, clientId: string, purposeId: string, isPrivateBucket: boolean }[] {
    return bucketConfigurations;
  },
  getBucketIdByKey(bucketName: string): string {
    const result = bucketConfigurations.find(bucket => bucket.bucketName === bucketName);
    return result ? result.bucketId : '';
  },
  set baseURL(url: string) {
    baseURL = url;
  },
  set cdnBaseURL(url: string) {
    cdnBaseURL = url;
  },
  set appCode(code: string) {
    appCode = code;
  },
  set region(reg: string) {
    region = reg;
  },
  set version(ver: string) {
    version = ver;
  },
  set cdnConfig(buckets: { bucketName: string, bucketId: string, clientId: string, purposeId: string, isPrivateBucket: boolean }[]) {
    bucketConfigurations = buckets;
  }
};
