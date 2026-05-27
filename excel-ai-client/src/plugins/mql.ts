import axios, { AxiosError } from "axios";
import Response from "@/plugins/response";
import { main } from "@/store/index";
import { MQLOptions } from "./mqlOptions";
import { toast } from "vue-sonner";
import Swal from "sweetalert2";

import type {
  AxiosInstance,
  InternalAxiosRequestConfig,
  AxiosResponse,
  CancelTokenSource,
} from "axios";

interface DialogConfirmParams {
  title: string;
  text: string;
  errMsg: string;
}

class MQL {
  strActivities: string | null;
  isQuery: boolean;
  isActivity: boolean;
  fetchableMap: Map<string, any>;
  version: string;
  region: string;
  appCode: string;
  activityType: string;
  mqlString: string;
  isConfirm: boolean;
  showPageLoader: boolean;
  mainStore: any;
  private CancelToken: CancelTokenSource;
  private mqlInstance: AxiosInstance;
  public ActivitySplitter = ".[";
  public ObjActivityNameKey = "ActivityName";
  public ObjActivityData = "Data";
  public QueryActivityKey = "FetchQueryData";
  public isDevelopment: boolean;
  constructor(strActivities: string | null = null) {
    this.isDevelopment = import.meta.env.VITE_NODE_ENV !== "production";
    this.strActivities = strActivities;
    this.isQuery = false;
    this.isActivity = false;
    this.fetchableMap = new Map();
    this.version = MQLOptions.version;
    this.region = MQLOptions.region;
    this.appCode = MQLOptions.appCode;
    this.activityType = "o";
    this.mqlString = "/mql";
    this.isConfirm = false;
    this.showPageLoader = true;
    this.mainStore = main();
    this.CancelToken = axios.CancelToken.source();
    this.mqlInstance = axios.create({
      baseURL: MQLOptions.baseURL,
    });

    this.mqlInstance.interceptors.request.use(
      (config: InternalAxiosRequestConfig): InternalAxiosRequestConfig => {
        if (
          config.url?.indexOf("r/mql") !== -1 ||
          config.url?.indexOf("r/c/mql") !== -1
        ) {
          if (sessionStorage.getItem("user-token") === null) {
            this.CancelToken.cancel(
              "user-token is not available, please login again"
            );
          }
        }
        return config;
      },
      (error: AxiosError): Promise<AxiosError> => {
        return Promise.reject(error);
      }
    );
  }

  formatActivity(activityStr: string): void {
    let activityArray: string[] = [];
    this.activityType = activityStr.split(this.ActivitySplitter)[0];
    this.fetchableMap.set("ActivityType", this.activityType);
    activityArray = activityStr
      .split(this.ActivitySplitter)[1]
      .slice(0, -1)
      .split(",");
    activityArray.forEach((item) => {
      const obj: any = {};
      let srvName: string;
      obj[this.ObjActivityData] = null;
      if (item.match(/query_/) !== null) {
        obj[item] = item.trim();
        srvName = item.trim();
        this.isQuery = true;
      } else {
        obj[this.ObjActivityNameKey] = item.trim();
        srvName = item.trim();
        this.isActivity = true;
      }
      this.fetchableMap.set(srvName, obj);
    });
  }

  deepFreeze<T>(object: T): T {
    const propNames = Object.getOwnPropertyNames(object);
    propNames.forEach((name) => {
      const value = (object as any)[name];
      (object as any)[name] =
        value && typeof value === "object" ? this.deepFreeze(value) : value;
    });
    return Object.freeze(object);
  }

  generateURL(activityType: string, customURL?: string | null): string {
    if (customURL != null && customURL !== undefined) {
      return (
        customURL +
        this.getVersion() +
        this.getRegion() +
        this.getAppCode() +
        this.getServiceURL(activityType)
      );
    } else {
      return (
        this.getVersion() +
        this.getRegion() +
        this.getAppCode() +
        this.getServiceURL(activityType)
      );
    }
  }

  getServiceURL(activityType: string): string {
    return (
      (activityType.toLowerCase() === "c"
        ? "r/" + activityType.toLowerCase()
        : activityType.toLowerCase()) + this.mqlString
    );
  }

  generateHeaders(
    activityType: string,
    activities: string,
    headers: Record<string, string> = {},
    isQuery: boolean = false
  ): Record<string, string> {
    headers["Service-Header"] = isQuery ? "FetchQueryData" : activities;
    if (activityType !== "o") {
      headers["Authorization"] =
        `Bearer ${sessionStorage.getItem("user-token")}`;
    }
    return headers;
  }

  getVersion(): string {
    return this.version ? `${this.version}/` : "";
  }

  getRegion(): string {
    return this.region ? `${this.region}/` : "";
  }

  getAppCode(): string {
    return this.appCode ? `${this.appCode}/` : "";
  }

  setActivity(strActivities: string | null = null): this {
    this.strActivities = strActivities;
    if (strActivities) {
      this.formatActivity(strActivities);
    }
    return this;
  }

  setData(strActivity: unknown | null = null, strDataObj: any = null): this {
    if (strActivity === null) {
    } else if (strDataObj === null) {
      // common data
      for (const [key, value] of this.fetchableMap) {
        if (value[this.ObjActivityData] === null) {
          value[this.ObjActivityData] = strActivity;
          this.fetchableMap.set(key, value);
        }
      }
    } else if (typeof strActivity == "string" && strActivity !== "") {
      // service specific
      const activityValue = this.fetchableMap.get(strActivity);
      activityValue[this.ObjActivityData] = strDataObj;
      this.fetchableMap.set(strActivity, activityValue);
    }
    return this;
  }

  setHeader(obj_header: Record<string, any> = {}): this {
    this.fetchableMap.set("MQLHeader", obj_header);
    return this;
  }

  setBranch(branch: string = "main"): this {
    this.fetchableMap.set("MQLHeader", { "Service-Branch": branch });
    return this;
  }

  setCustomURL(str_customURL: string | null = null): this {
    this.fetchableMap.set("CustomURL", str_customURL);
    return this;
  }

  showConfirmDialog(boolConfirmation: boolean = false): this {
    this.isConfirm = boolConfirmation;
    return this;
  }

  enablePageLoader(boolShowPageLoader: boolean = false): this {
    this.showPageLoader = boolShowPageLoader;
    return this;
  }

  setLoginActivity(): this {
    this.setActivity("o.[ldapLogin]");
    return this;
  }

  fetch(docId: string | null = null): Promise<AxiosResponse<any> | unknown> {
    return new Promise((resolve) => {
      if (this.isConfirm) {
        dialogConfirm({
          title: "Confirmation",
          text: "Are you sure you want to continue?",
          errMsg: "Cancelled by User",
        })
          .then(() => resolve(this.run(docId)))
          .catch((e) =>
            resolve({
              data: { error: e.message, errorCode: 1990, result: null },
            })
          );
      } else {
        resolve(this.run(docId));
      }
    }).catch((error) => {
      if (import.meta.env.NODE_ENV !== "production") {
        toast.error("Error", { description: error });
      }
    });
  }

  run(docId: string | null = null): Promise<AxiosResponse<any> | unknown> {
    return new Promise((resolve) => {
      if (this.showPageLoader && this.mainStore) {
        this.mainStore.MUTATE_PAGE_BLOCKER(true);
      }

      let postParamObject: Record<string, any> = {};
      let activities = "";
      const payloadObject: Record<string, any> = {};
      for (const [key, value] of this.fetchableMap) {
        if (
          key.search("ActivityType") < 0 &&
          key.search("MQLHeader") < 0 &&
          key.search("CustomURL") < 0 &&
          key.search("isQuery") < 0
        ) {
          activities += "," + key;
          const formattedKey =
            key.match(/query_/) && key.match(/query_/)!.length > 0
              ? key.substring("query_".length)
              : key;
          payloadObject[formattedKey] = value.Data;
        }
      }

      if (this.isQuery) {
        payloadObject["fetchGroup"] = activities
          .substring(1) // Remove leading comma
          .split(",")
          .map((item) => item.substring("query_".length));
        postParamObject[this.QueryActivityKey] = payloadObject;
      } else {
        postParamObject = payloadObject;
      }
      this.mqlInstance({
        url: this.generateURL(
          this.activityType,
          this.fetchableMap.get("CustomURL")
        ),
        method: "POST",
        headers: this.generateHeaders(
          this.activityType,
          activities.slice(1),
          this.fetchableMap.get("MQLHeader"),
          this.isQuery
        ),
        data: postParamObject,
        cancelToken: this.CancelToken.token,
      })
        .then((res) => {
          if (this.showPageLoader) {
            this.mainStore.MUTATE_PAGE_BLOCKER(false);
          }
          resolve(new Response(res));
        })
        .catch((error) => {
          if (this.showPageLoader) {
            this.mainStore.MUTATE_PAGE_BLOCKER(false);
          }
          resolve(
            new Response({
              data: {
                error: error.message,
                errorCode: 1990,
                result: null,
              },
            })
          );
        });
    }).catch((error) => {
      if (import.meta.env.NODE_ENV !== "production") {
        toast.error("Error", { description: error });
      }
    });
  }
}
function dialogConfirm({
  title,
  text,
  errMsg,
}: DialogConfirmParams): Promise<void> {
  return new Promise((resolve, reject) => {
    Swal.fire({
      title: title,
      text: text,
      confirmButtonText: "Yes",
      showCancelButton: true,
      cancelButtonText: "Cancel",
    }).then((obj) => {
      if (obj.isConfirmed) {
        resolve();
      } else {
        reject(new Error(errMsg));
      }
    });
  });
}

export default MQL;
