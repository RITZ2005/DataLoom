import router from "@/router/router";
import { toast } from "vue-sonner";
// Define interfaces for the structure of your raw data and headers
interface RawData {
  data: any; // Define a more specific type if possible
  headers?: {
    authorization?: string; // Make this optional as it may not always exist
    [key: string]: any; // Allow other headers
  };
  errorCode?: number; // Include error code if relevant
  FetchQueryData?: {
    result: { [key: string]: any }; // Define more specific structure if possible
    errorCode?: number;
    error?: string;
  };
  [key: string]: any; // Allow other properties
}

class Response {
  private raw: RawData;
  private headers: RawData["headers"];
  private isReactive: boolean;

  constructor(objRaw: RawData) {
    this.raw = objRaw.data;
    this.headers = objRaw.headers;
    this.isReactive = false;

    if (this.headers?.authorization) {
      sessionStorage.setItem("user-token", this.headers.authorization);
    }
  }

  setReactivity(isReactive: boolean): void {
    this.isReactive = isReactive;
  }

  private deepFreeze(object: any): any {
    // Retrieve the property names defined on the object
    if (object === undefined || object === null) {
      return object;
    }
    const propNames = Object.getOwnPropertyNames(object);
    // Freeze properties before freezing self
    for (const name of propNames) {
      const value = object[name];
      object[name] =
        value && typeof value === "object" ? this.deepFreeze(value) : value;
    }
    return Object.freeze(object);
  }

  getRaw(isReactive: boolean = false): any {
    return isReactive ? this.raw : this.deepFreeze(this.raw);
  }

  getHeaders(): RawData["headers"] {
    return this.headers;
  }

  showElement(strDocId: string | null): void {
    if (strDocId != null) {
      const element = document.getElementById(strDocId);
      if (element && element.style.display === "none") {
        element.style.display = "block";
      }
    }
  }

  hideElement(strDocId: string | null): void {
    if (strDocId != null) {
      const element = document.getElementById(strDocId);
      if (element) {
        element.style.display = "none";
      }
    }
  }

  getActivity(strActivity: string, isReactive: boolean = false): any {
    if (strActivity.split("_").length > 1) {
      return isReactive
        ? this.raw.FetchQueryData?.result[
            strActivity.substring("query_".length)
          ]
        : this.deepFreeze(
            this.raw.FetchQueryData?.result[
              strActivity.substring("query_".length)
            ]
          );
    } else {
      return isReactive
        ? this.raw[strActivity]
        : this.deepFreeze(this.raw[strActivity]);
    }
  }

  NavigateTo(strRoute: string): void {
    router.push(strRoute);
  }

  isValid(strActivity: string | null = null): boolean {
    if (strActivity === null) {
      return !!(this.raw.errorCode === 1000 || this.raw.errorCode === 0);
    } else {
      if (strActivity.split("_").length > 1) {
        return !!(
          this.raw.FetchQueryData?.errorCode === 1000 ||
          this.raw.FetchQueryData?.errorCode === 0
        );
      } else {
        return !!(
          this.raw[strActivity]?.errorCode === 1000 ||
          this.raw[strActivity]?.errorCode === 0
        );
      }
    }
  }

  uploadedFileURL(): any {
    return this.raw.result;
  }

  getAssetPath(): string {
    return this.raw.result.path; // returns path where your asset is stored
  }

  showErrorToast(strActivity: string | null = null): this {
    const getErrorDescription = (activity: string | null): string => {
      if (activity === null) {
        return this.raw.error;
      }
      if (activity.split("_").length > 1) {
        return this.raw.FetchQueryData?.error || this.raw.error;
      }
      return this.raw[activity]?.error || this.raw.error;
    };

    toast.error("Error", { description: getErrorDescription(strActivity) });
    return this;
  }
}

export default Response;
