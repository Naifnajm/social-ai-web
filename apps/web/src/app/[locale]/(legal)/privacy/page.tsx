import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { CONTACT_EMAIL, LegalDoc, type LegalText, OPERATOR } from "../legal-doc";

const EN: LegalText = {
  title: "Privacy Policy",
  updated: "Effective 12 November 2026",
  intro: `Stravica Social (social.stravica.nl) is operated by ${OPERATOR}. It helps businesses create, schedule and publish social media posts, and answer the messages and comments they receive, in one place. This policy explains what data we process, why, and the choices you have.`,
  sections: [
    { title: "1. Data we process", body: [
      "Account data: your name, e-mail address or username, password (stored only as a secure hash), language and workspace membership.",
      "Content you create: posts, captions, images and videos, schedules, campaigns, links and brand settings stored in your workspace.",
      "Connected social accounts: when you connect Facebook, Instagram, X, LinkedIn, TikTok, YouTube, Pinterest, Threads, Telegram, WhatsApp or Google Business Profile, we store the account identifiers and the access tokens the network gives us (encrypted), and the permissions you granted.",
      "Messages and comments: for accounts with the inbox switched on, we receive and store the direct messages and comments sent to your pages and profiles, with the sender's public name, username and profile picture as provided by the network, so your team can read and answer them.",
      "Usage and technical data: logs needed to run and secure the service (for example error reports). Link-click statistics are counted without storing IP addresses.",
    ] },
    { title: "2. How we use data", body: [
      "To provide the service you asked for: publishing your posts, showing your statistics, and showing and sending replies in your inbox.",
      "AI features: when you use AI writing, image or reply suggestions, the text or media involved is sent to the AI provider configured for your workspace (for example OpenAI, Anthropic or Google) only to produce that result.",
      "To keep the service secure, prevent abuse, and provide support when you contact us.",
      "We do not sell personal data and we do not use data received from Meta or other networks for advertising.",
    ] },
    { title: "3. Data from Meta (Facebook, Instagram, Messenger)", body: [
      "We use Meta's APIs only for the features you switch on: publishing to your Pages and Instagram accounts, reading their insights, and reading and answering their messages and comments.",
      "Page and Instagram data is used only inside the workspace that connected the account and is never shared with other customers.",
      "You can remove our access at any time in Facebook Settings → Apps and Websites, or by disconnecting the account in Stravica Social (Settings → Accounts).",
    ] },
    { title: "4. Sharing", body: [
      "We share data only with service providers that help us run the service (hosting, e-mail delivery, payment processing through Stripe, and the AI providers you choose), under agreements that protect it, or when the law requires it.",
    ] },
    { title: "5. Retention and deletion", body: [
      "We keep your data while your account is active. When you disconnect a social account its access tokens are deleted. When your account is deleted, your workspace data is erased within 30 days, except where the law requires us to keep certain records (for example invoices).",
      "See the Data Deletion page (social.stravica.nl/data-deletion) for how to request deletion.",
    ] },
    { title: "6. Security", body: [
      "Access tokens and secrets are stored encrypted, connections use HTTPS, and access to production systems is restricted.",
    ] },
    { title: "7. Your rights", body: [
      "Depending on where you live (including under the EU GDPR) you can ask to access, correct, export or delete your personal data, object to or restrict its processing, and lodge a complaint with your data protection authority.",
      `To exercise these rights, e-mail ${CONTACT_EMAIL}. We answer within 30 days.`,
    ] },
    { title: "8. Changes", body: [
      "If we change this policy we will update this page and the date above, and tell account owners about important changes.",
    ] },
  ],
};

const AR: LegalText = {
  title: "سياسة الخصوصية",
  updated: "سارية من 12 نوفمبر 2026",
  intro: `تُشغّل ${OPERATOR} منصة Stravica Social (social.stravica.nl)، وهي تساعد الأعمال على إنشاء منشورات التواصل الاجتماعي وجدولتها ونشرها، والرد على الرسائل والتعليقات في مكان واحد. توضّح هذه السياسة البيانات التي نعالجها ولماذا، والخيارات المتاحة لك.`,
  sections: [
    { title: "1. البيانات التي نعالجها", body: [
      "بيانات الحساب: الاسم، والبريد الإلكتروني أو اسم المستخدم، وكلمة المرور (تُحفظ مشفّرة تشفيراً أحادياً فقط)، واللغة، وعضوية مساحة العمل.",
      "المحتوى الذي تنشئه: المنشورات والنصوص والصور والفيديوهات والجداول والحملات والروابط وإعدادات العلامة التجارية.",
      "الحسابات المربوطة: عند ربط فيسبوك أو إنستغرام أو X أو LinkedIn أو TikTok أو YouTube أو Pinterest أو Threads أو Telegram أو WhatsApp أو Google Business Profile نحفظ معرّفات الحساب ورموز الوصول التي تمنحها المنصة (مشفّرة) والصلاحيات التي وافقت عليها.",
      "الرسائل والتعليقات: للحسابات المفعّل لها صندوق الوارد نستقبل الرسائل الخاصة والتعليقات الموجّهة لصفحاتك وحساباتك ونحفظها مع الاسم العام للمرسل واسم المستخدم وصورة ملفه كما توفّرها المنصة، ليتمكن فريقك من قراءتها والرد عليها.",
      "بيانات الاستخدام والبيانات التقنية: السجلات اللازمة لتشغيل الخدمة وحمايتها. وتُحتسب نقرات الروابط دون حفظ عناوين IP.",
    ] },
    { title: "2. كيف نستخدم البيانات", body: [
      "لتقديم الخدمة التي طلبتها: نشر منشوراتك، وعرض إحصاءاتك، وعرض الرسائل وإرسال الردود في صندوق الوارد.",
      "ميزات الذكاء الاصطناعي: عند استخدامها يُرسل النص أو الوسائط المعنية إلى مزوّد الذكاء الاصطناعي المحدد لمساحة عملك (مثل OpenAI أو Anthropic أو Google) لإنتاج النتيجة فقط.",
      "لحماية الخدمة ومنع إساءة الاستخدام وتقديم الدعم عند تواصلك معنا.",
      "لا نبيع البيانات الشخصية، ولا نستخدم البيانات الواردة من ميتا أو غيرها من المنصات للإعلانات.",
    ] },
    { title: "3. البيانات الواردة من ميتا (فيسبوك وإنستغرام وماسنجر)", body: [
      "نستخدم واجهات ميتا فقط للميزات التي تفعّلها: النشر على صفحاتك وحسابات إنستغرام، وقراءة إحصاءاتها، وقراءة رسائلها وتعليقاتها والرد عليها.",
      "تُستخدم بيانات الصفحة وإنستغرام داخل مساحة العمل التي ربطت الحساب فقط، ولا تُشارك مع أي عميل آخر.",
      "يمكنك إلغاء وصولنا في أي وقت من إعدادات فيسبوك ← التطبيقات ومواقع الويب، أو بإلغاء ربط الحساب في المنصة (الإعدادات ← الحسابات).",
    ] },
    { title: "4. المشاركة", body: [
      "نشارك البيانات فقط مع مزوّدي الخدمات الذين يساعدوننا على تشغيل المنصة (الاستضافة، وإرسال البريد، والدفع عبر Stripe، ومزوّدي الذكاء الاصطناعي الذين تختارهم) بموجب اتفاقيات تحميها، أو عندما يفرض القانون ذلك.",
    ] },
    { title: "5. الاحتفاظ والحذف", body: [
      "نحتفظ ببياناتك ما دام حسابك نشطاً. عند إلغاء ربط حساب تواصل تُحذف رموز الوصول الخاصة به. وعند حذف حسابك تُمسح بيانات مساحة العمل خلال 30 يوماً، إلا ما يُلزمنا القانون بالاحتفاظ به (مثل الفواتير).",
      "راجع صفحة حذف البيانات (social.stravica.nl/data-deletion) لمعرفة طريقة طلب الحذف.",
    ] },
    { title: "6. الأمان", body: [
      "تُحفظ رموز الوصول والأسرار مشفّرة، وتمر الاتصالات عبر HTTPS، والوصول إلى أنظمة التشغيل مقيّد.",
    ] },
    { title: "7. حقوقك", body: [
      "حسب مكان إقامتك (ومنها اللائحة الأوروبية GDPR) يحق لك طلب الاطلاع على بياناتك أو تصحيحها أو تصديرها أو حذفها، والاعتراض على معالجتها أو تقييدها، وتقديم شكوى لهيئة حماية البيانات.",
      `لممارسة هذه الحقوق راسلنا على ${CONTACT_EMAIL}، ونرد خلال 30 يوماً.`,
    ] },
    { title: "8. التغييرات", body: [
      "عند تعديل هذه السياسة نحدّث هذه الصفحة والتاريخ أعلاه، ونُبلغ أصحاب الحسابات بالتغييرات المهمة.",
    ] },
  ],
};

export const metadata: Metadata = { title: "Privacy Policy" };

export default async function PrivacyPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <LegalDoc doc={locale === "ar" ? AR : EN} />;
}
