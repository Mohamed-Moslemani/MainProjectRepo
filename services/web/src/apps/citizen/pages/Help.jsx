import { Link } from 'react-router-dom';
import flagImg from '@shared/assets/Figure_1.png';
import '@shared/styles/dashboard.css';
import L from '@shared/components/L';

/**
 * Static FAQ / help / terms / privacy page.
 *
 * Three thin sections rendered from a single page. The route
 * accepts an optional anchor (#faq, #terms, #privacy) so links
 * elsewhere in the app can deep-link into a specific section.
 *
 * Content is intentionally short and answers the questions citizens
 * actually ask: what docs do I need, why is the AI involved, what
 * happens to my photos, how do I track my application, what does
 * the mukhtar do.
 */

const FAQ = [
  {
    q_ar: 'ما هي المستندات المطلوبة لتجديد جواز السفر؟',
    q_en: 'What documents do I need to renew my passport?',
    a_ar:
      'صفحة بيانات الجواز القديم، إخراج قيد عائلي حديث، صورة شخصية واضحة، وتحقق من الحياة عبر الكاميرا. قد يُطلب أحياناً صورة عن الهوية الوطنية.',
    a_en:
      'The biometric data page of your old passport, a recent civil registry extract (إخراج قيد), a clear selfie, and a camera-based liveness check. A national ID front photo is sometimes requested too.',
  },
  {
    q_ar: 'ما الذي يفعله الذكاء الاصطناعي بطلبي؟',
    q_en: 'What does the AI do with my application?',
    a_ar:
      'يقرأ النصوص من المستندات (OCR)، يتحقق من تطابق الصور مع وجهك (مقارنة الوجوه)، ويطابق بياناتك مع سجل القيد المدني. كل قرار آلي يُسجَّل ويمكن مراجعته يدوياً.',
    a_en:
      'It reads text from your documents (OCR), checks that your selfie matches the photo on your passport (face verification), and cross-checks the values you typed against the civil registry. Every automated decision is logged and can be manually reviewed.',
  },
  {
    q_ar: 'ماذا يحدث إذا كانت الصورة غير واضحة؟',
    q_en: 'What if my photo is blurry?',
    a_ar:
      'سيُطلب منك إعادة الالتقاط — لن تذهب الصور غير الواضحة إلى الموظف. تأكّد من إضاءة جيدة، وضع المستند على سطح داكن، وعدم وجود انعكاسات.',
    a_en:
      'You\'ll be asked to retake it — blurry photos never reach an officer. Use bright even lighting, place the document on a dark surface, and avoid glare or shadow.',
  },
  {
    q_ar: 'كيف أتتبع حالة طلبي؟',
    q_en: 'How do I track my application?',
    a_ar:
      'كل طلب له رقم تتبع يبدأ بـ DFL-. يمكنك إدخاله في صفحة التتبع العامة دون تسجيل دخول، أو رؤية كل التفاصيل من حسابك.',
    a_en:
      'Every application gets a tracking ID that starts with DFL-. You can paste it on the public tracking page without logging in, or see full details from your account.',
  },
  {
    q_ar: 'ما هو دور المختار؟',
    q_en: 'What does the mukhtar do?',
    a_ar:
      'لطلبات جواز السفر، يصدّق المختار على ثلاثة أمور: أنك مقيم في منطقته، وأن الصورة المُقدَّمة تطابقك، وأنك حضرت شخصياً لتقديم الطلب — كما هو الحال مع الاستمارة الورقية اليوم.',
    a_en:
      'For passport applications the mukhtar attests to three things: that you live in their locality, that the submitted photo matches you, and that you were physically present to sign — the same legal attestation they sign on the paper form today.',
  },
  {
    q_ar: 'ما هي رسوم الخدمة؟',
    q_en: 'What are the service fees?',
    a_ar:
      'رسوم رمزية لاسترداد كلفة المعالجة، تُدفَع عبر بطاقة ائتمان بعد الموافقة على الطلب. تُعرض الرسوم بدقة قبل الدفع.',
    a_en:
      'A small processing fee, charged by card after your application is approved. The exact amount is shown before payment.',
  },
  {
    q_ar: 'ما الذي يحدث بعد الموافقة؟',
    q_en: 'What happens after approval?',
    a_ar:
      'تدفع الرسوم، ينتقل الطلب إلى مرحلة الإنتاج، ثم يصبح جاهزاً للاستلام من المركز. ستتلقى إشعاراً في كل خطوة.',
    a_en:
      'You pay the fee, the application moves into production, then becomes ready for pickup at the issuing centre. You\'ll get a notification at every step.',
  },
];

export default function Help() {
  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="dashboard-header__inner">
          <div className="dashboard-header__brand">
            <img src={flagImg} alt="" className="dashboard-header__flag" />
            <div>
              <h1 className="dashboard-header__title"><L ar="المساعدة" en="Help &amp; FAQ" /></h1>
            </div>
          </div>
          <div className="dashboard-header__actions">
            <Link to="/dashboard" className="btn btn--outline btn--sm">
              <L ar="الرئيسية" en="· Dashboard" />
            </Link>
          </div>
        </div>
      </header>

      <main className="dashboard-main" style={{ maxWidth: 760 }}>
        <nav style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
          <a href="#faq" className="btn btn--ghost btn--sm">
            <L ar="الأسئلة الشائعة" en="FAQ" />
          </a>
          <a href="#terms" className="btn btn--ghost btn--sm">
            <L ar="شروط الاستخدام" en="Terms of Use" />
          </a>
          <a href="#privacy" className="btn btn--ghost btn--sm">
            <L ar="الخصوصية" en="Privacy" />
          </a>
          <a href="#contact" className="btn btn--ghost btn--sm">
            <L ar="تواصل معنا" en="Contact" />
          </a>
        </nav>

        <section id="faq" className="detail-section">
          <h2>
            <L ar="الأسئلة الشائعة" en="Frequently Asked Questions" />
          </h2>
          <dl style={{ display: 'flex', flexDirection: 'column', gap: '1rem', marginTop: '0.75rem' }}>
            {FAQ.map((item) => (
              <div key={item.q_en}>
                <dt style={{ fontWeight: 700, color: '#1f2937' }}>
                  <L>{{ ar: <>{item.q_ar}</>, en: <>{item.q_en}</> }}</L>
                </dt>
                <dd style={{ marginTop: '0.4rem', marginInlineStart: 0, color: '#374151', lineHeight: 1.6 }}>
                  <L>{{ ar: <>{item.a_ar}</>, en: <>{item.a_en}</> }}</L>
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <section id="terms" className="detail-section">
          <h2>
            <L ar="شروط الاستخدام" en="Terms of Use" />
          </h2>
          <L>{{ ar: <>باستخدامك منصة DocFlow Lebanon فإنك توافق على تقديم بيانات صحيحة قابلة للتحقق، وعلى أن
            تكون المستندات المرفوعة أصلية وتعود لك. يحقّ للمنصة رفض الطلبات المشبوهة أو غير المكتملة
            وإحالتها للمراجعة اليدوية.</>, en: <>By using DocFlow Lebanon you agree to provide accurate, verifiable information and that
            every uploaded document is genuine and yours. The platform may reject suspicious or
            incomplete applications and route them to manual review.</> }}</L>
        </section>

        <section id="privacy" className="detail-section">
          <h2>
            <L ar="الخصوصية" en="Privacy" />
          </h2>
          <L>{{ ar: <>نحتفظ ببياناتك الشخصية فقط للمدة اللازمة لمعالجة الطلب وإصدار الوثيقة. الصور لا تُشارَك
            خارج النظام. كل قرار آلي يُسجَّل في سجل التدقيق ويمكن مراجعته. أسماء المواطنين وتواريخ
            الولادة لا تُسجَّل بنصها الصريح في سجلات النظام بل تُخفى تقنياً.</>, en: <>We retain your personal data only for as long as needed to process the application and
            issue the document. Photos are never shared outside the system. Every automated decision
            is recorded in an audit log and can be reviewed. Names, dates of birth, and other PII
            are technically redacted in our internal logs.</> }}</L>
        </section>

        <section id="contact" className="detail-section">
          <h2>
            <L ar="التواصل" en="Contact" />
          </h2>
          <p style={{ color: '#374151', lineHeight: 1.6 }}>
            <L>{{ ar: <>للأسئلة التقنية أو مشاكل في الطلب، تواصل مع الدعم على
              {' '}<a href="mailto:support@docflow.lb">support@docflow.lb</a>.</>, en: <>For technical issues or questions about your application, email{' '}
              <a href="mailto:support@docflow.lb">support@docflow.lb</a>.</> }}</L>
          </p>
        </section>
      </main>
    </div>
  );
}
