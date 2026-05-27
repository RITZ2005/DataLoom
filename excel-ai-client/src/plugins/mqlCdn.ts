import axios from 'axios';
import type { AxiosInstance, AxiosRequestConfig, CancelTokenSource } from 'axios';
import Response from '@/plugins/response';
import { MQLOptions } from "./mqlOptions";
import { toast } from "vue-sonner";
import { main } from '@/store/index';


class MQLCdn {
  private fileName: string = '';
  private formData: FormData = new FormData();
  private clientId: string = '';
  private bucketName: string = '';
  private isPrivateBucket: boolean = false;
  private cdnURL: string = '';
  private cdnPath: string = '';
  private showPageLoader: boolean = false;
  private mqlInstance: AxiosInstance;
  private cancelTokenSource?: CancelTokenSource;

  private mainStore = main();
  constructor() {
    this.formData.set('enctype', 'multipart/form-data');
    this.mqlInstance = axios.create({
      baseURL: MQLOptions.cdnBaseURL,
    });
    // TODO: This is a temporary fix. Need to find a better way to get the current branch.
    //   this.mqlInstance.interceptors.request.use(
    //     (config: AxiosRequestConfig) => {
    //       if (localStorage.getItem('user-token') === null) {
    //         this.cancelTokenSource?.cancel('Operation canceled by the MQLCDN interceptor.');
    //       }
    //       return config;
    //     },
    //     (error) => Promise.reject(error)
    //   );
  }

  private setHeaders(headers: Record<string, string> = {}): Record<string, string> {
    headers['Authorization'] = `Bearer ${localStorage.getItem('user-token')}`;
    return headers;
  }

  uploadFile(docId: string | null = null): Promise<Response> {
    this.cdnURL = `${this.clientId}/uploadFile`;
    let originalText = '';

    if (this.showPageLoader) {
      this.mainStore.MUTATE_PAGE_BLOCKER(true);
    }

    return new Promise((resolve) => {
      if (docId && document.getElementById(docId)) {
        const element = document.getElementById(docId) as HTMLButtonElement;
        originalText = element.innerHTML;
        element.disabled = true;
        element.innerHTML = 'Processing';
      }

      this.prepareMQLCDNRequest('POST', docId, originalText)
        .then((cdnResponse) => {
          if (this.showPageLoader) {
            this.mainStore.MUTATE_PAGE_BLOCKER(false);
          }
          resolve(cdnResponse);
        })
        .catch((error) => {
          toast.error("Error", { description: 'Upload failed:' + error.message, class: "bg-red-500 text-white" });
        });
    });
  }

  downloadFile(docId: string | null = null): Promise<void> {
    if (this.cdnPath.startsWith('http://') || this.cdnPath.startsWith('https://')) {
      this.cdnURL = this.cdnPath;
    } else {
      this.cdnURL = `${window.location.origin}${MQLOptions.cdnBaseURL}${this.cdnPath}`;
    }

    let originalText = '';

    if (this.showPageLoader) {
      this.mainStore.MUTATE_PAGE_BLOCKER(true);
    }

    if (docId && document.getElementById(docId)) {
      const element = document.getElementById(docId) as HTMLButtonElement;
      originalText = element.innerHTML;
      element.disabled = true;
      element.innerHTML = 'Processing';
    }

    return new Promise((resolve) => {
      // TODO:add the client id check using this.clientId
      if (MQLOptions.cdnConfig.length > 0 && MQLOptions.cdnConfig[0].clientId) {
        this.mqlInstance({
          url: this.cdnURL,
          method: 'GET',
          headers: this.setHeaders(),
          responseType: 'blob',
          cancelToken: (this.cancelTokenSource = axios.CancelToken.source()).token,
        })
          .then((res) => {
            if (this.showPageLoader) {
              this.mainStore.MUTATE_PAGE_BLOCKER(false);
            }

            if (docId && document.getElementById(docId)) {
              const element = document.getElementById(docId) as HTMLButtonElement;
              element.disabled = false;
              element.innerHTML = originalText;
            }

            this.fileName = this.getFilenameFromUrl(this.cdnURL);
            const url = window.URL.createObjectURL(new Blob([res.data]));
            const a = document.createElement('a');
            a.href = url;
            a.download = this.fileName;
            a.target = '_blank';
            a.click();
            resolve();
          })
          .catch((error) => {
            if (this.showPageLoader) {
              this.mainStore.MUTATE_PAGE_BLOCKER(false);
            }
            console.error('Download failed:', error.message);
          });
      } else {
        console.error('Invalid Bucket Key');
      }
    });
  }

  private getFilenameFromUrl(url: string): string {
    const pathname = new URL(url).pathname;
    const index = pathname.lastIndexOf('/');
    return index !== -1 ? pathname.substring(index + 1) : pathname;
  }

  setFileName(fileName: string): this {
    this.fileName = fileName.trim();
    this.formData.append('fileName', this.fileName);
    return this;
  }

  setCDNPath(cdnPath: string): this {
    this.cdnPath = cdnPath;
    return this;
  }

  setFormData(formData: FormData): this {
    this.formData = formData;
    return this;
  }

  enablePageLoader(show: boolean): this {
    this.showPageLoader = show;
    return this;
  }

  setBucketKey(bucketName: string): this {
    this.bucketName = bucketName;
    this.fetchBucketIdFromKey(bucketName);
    return this;
  }

  private fetchBucketIdFromKey(bucketName: string): void {
    const bucketObj: { clientId: string; isPrivateBucket: boolean } | undefined = { clientId: "", isPrivateBucket: false }
    if (bucketObj) {
      this.clientId = bucketObj.clientId;
      this.isPrivateBucket = bucketObj.isPrivateBucket;
    } else {
      this.clientId = '';
    }
  }

  private prepareMQLCDNRequest(
    requestType: 'GET' | 'POST',
    docId: string | null,
    originalText: string
  ): Promise<Response> {
    return new Promise((resolve) => {
      if (this.clientId) {
        this.mqlInstance({
          url: this.cdnURL,
          method: requestType,
          headers: this.setHeaders(),
          data: this.formData,
          cancelToken: (this.cancelTokenSource = axios.CancelToken.source()).token,
        })
          .then((res) => {
            if (this.showPageLoader) {
              this.mainStore.MUTATE_PAGE_BLOCKER(false);
            }
            resolve(new Response({ data: res.data, errorCode: 1000, result: res.data }));
          })
          .catch((error) => {
            console.error('Request failed:', error.message);
          });
      } else {
        console.error('Invalid Bucket Key');
      }
    });
  }
}

export default MQLCdn;
