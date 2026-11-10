import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

export default createMiddleware(routing);

export const config = {
  // every path except the API, Next internals and files
  matcher: ["/((?!api|_next|_vercel|m/|.*\\..*).*)"],
};
