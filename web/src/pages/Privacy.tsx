/**
 * DRAFT — مسودة سياسة الخصوصية
 * تهميش هام: هذه الوثيقة مسودة تقنية خاضعة للمراجعة والاعتماد القانوني من قبل إدارة أساس AI قبل الإطلاق الرسمي.
 * لا تمثل هذه الصفحة استشارة قانونية.
 */
import { Card, Icon, Swash } from '../asaas-ui';
import { usePageMeta } from '../lib/usePageMeta';

export default function Privacy() {
  usePageMeta({
    title: 'سياسة الخصوصية — وكلاء أساس',
    description: 'سياسة الخصوصية وحماية بيانات الزوار في منصة وكلاء أساس (ASAAS Agents Platform).',
  });

  return (
    <div className="page-legal" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--gutter, 20px)' }}>
      {/* Notice Banner */}
      <div
        style={{
          padding: '12px 18px',
          borderRadius: 'var(--radius-md)',
          background: 'var(--glass-tint)',
          border: '1px solid var(--accent)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          fontSize: '13.5px',
          color: 'var(--text-1)',
        }}
      >
        <Icon name="alert" />
        <span>
          <strong>مسودة للمراجعة القانونية:</strong> تم إعداد هذه السياسة لتوثيق السلوك التقني الفعلي للمنصة بدقة، وهي خاضعة للمراجعة والاعتماد من قبل الإدارة القانونية لشركة أساس AI قبل النشر النهائي.
        </span>
      </div>

      <Card style={{ padding: '28px' }}>
        <h1 className="title" style={{ margin: '0 0 8px 0', fontSize: '26px' }}>
          سياسة الخصوصية وحماية المفاتيح
          <Swash>.</Swash>
        </h1>
        <p className="subtle" style={{ margin: '0 0 24px 0', fontSize: '14px' }}>
          آخر تحديث تقني: نوفمبر 2026 | الإصدار 1.0 (مرشح للإطلاق)
        </p>

        <div className="prose" style={{ lineHeight: 1.8, color: 'var(--text-1)', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>1. المبدأ الأساسي: بدون حسابات وبدون تتبع شخصي</h2>
            <p style={{ margin: 0 }}>
              منصة <strong>وكلاء أساس (ASAAS Agents Platform)</strong> هي منصة استعراض تقني عامة لا تتطلب إنشاء حساب، ولا تسجيل دخول، ولا جمع أي بيانات شخصية (كالاسم، البريد الإلكتروني، أو أرقام الهواتف). كل تجربة تفاعلية تبدأ وتنتهي ضمن جلسة التصفح الحالية للزائر.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>2. نموذج استخدام المفتاح الخاص (BYOK) ومعالجة مفاتيح API</h2>
            <p style={{ margin: 0 }}>
              لكي يتمكن الزائر من تجربة أي وكيل بشكل حي، يُطلب منه إدخال مفتاح API الخاص به والمملوك له لدى أحد المزودين المعتمدين (مثل Google AI Studio، OpenAI، Anthropic، OpenRouter). نلتزم بالضوابط الأمنية الصارمة التالية:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li><strong>عدم التخزين نهائياً:</strong> لا يتم تخزين مفتاح API الخاص بك على الإطلاق في أي قاعدة بيانات، أو سجلات تشغيل (Logs)، أو ملفات خادم، أو أنظمة تحليلات.</li>
              <li><strong>نقل مشفر عبر HTTPS:</strong> يُرسل المفتاح مباشرة من متصفحك عبر اتصال مشفر وآمن ولا يمر إلا في الذاكرة المؤقتة (In-Memory) لخادم أساس أثناء معالجة الطلب الموجه لمزود الخدمة.</li>
              <li><strong>عزل الوكلاء (Process Isolation):</strong> عملية الوكيل (Agent Subprocess) التي تنفذ الكود البرمجي <strong>لا تستلم مفتاحك الحقيقي أبداً</strong>. الخادم يولد رمزاً مؤقتاً خاصاً بالتجربة الحالية فقط (Ephemeral Token)، ويقوم وسيط الخادم بحقن المفتاح عند الاتصال بالمزود مباشرة.</li>
              <li><strong>انتهاء الصلاحية الفوري:</strong> يُلغى الرمز المؤقت وتُمسح بيانات الجلسة فور انتهاء التجربة أو إغلاقك للمتصفح.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>3. معالجة المدخلات والملفات المرفوعة وفحص المواقع</h2>
            <p style={{ margin: 0 }}>
              عند إدخال نصوص أو رفع مستندات أو تزويد وكلاء فحص المواقع (مثل Site DNA) بروابط نطاقات إلكترونية:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li>يتم فحص الملفات المرفوعة والتحقق من بصمتها الرقمية ومحتواها (Magic Bytes) قبل تمريرها للوكيل.</li>
              <li><strong>فحص المواقع العامة فقط:</strong> يقتصر زحف وتصفح المواقع على النطاقات العامة المتاحة (بحد أقصى 8 صفحات لكل جولة)، مع الالتزام الصارم بملفات <code>robots.txt</code>، وحظر كافة عناوين IP المباشرة وعناوين الشبكات الداخلية (Localhost / RFC 1918 / Cloud Metadata). عند تفعيل مرحلة «استخبارات المنافسين» اختيارياً (وهي معطّلة افتراضياً)، قد يجلب الوكيل أيضاً صفحات عامة لمواقع منافسة ذات صلة.</li>
              <li><strong>جلسات وكلاء الخدمات المؤقتة (Session Cookie):</strong> لإتاحة واجهات الوكلاء التفاعلية وعزل نتائج التحاليل والتقارير بين المستخدمين، يُستخدم ملف تعريف ارتباط تقني مؤقت حصري (<code>asaas_service_session</code>، بخاصيتي <code>HttpOnly</code> و <code>SameSite=Strict</code>). ينتهي هذا الملف تلقائياً عند انتهاء مهلة الجلسة (45 دقيقة خمول / ساعتان كحد أقصى) ولا يُستخدم إطلاقاً لأي تتبع تسويقي أو تحليلي.</li>
              <li><strong>الاحتفاظ المؤقت بالملفات وحذفها الآلي (60 دقيقة):</strong> تُحفظ مخرجات التحليل المؤقتة (لقطات الشاشة وتقارير HTML/PDF) في بيئة معزولة لكل جلسة فقط، وتُحذف تلقائياً عبر منظومة التنظيف الآلي (Janitor) بعد <strong>60 دقيقة</strong> من انتهاء الجولة أو فور انتهاء الجلسة أو تجاوز حصة التخزين.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>4. مزودو خدمات الذكاء الاصطناعي الخارجيون</h2>
            <p style={{ margin: 0 }}>
              يتم توجيه طلبات استنتاج النماذج إلى المزود الذي اخترته باستخدام مفتاحك الخاص. يخضع استخدام تلك الخدمات لسياسات الخصوصية وشروط الاستخدام الخاصة بكل مزود:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li>Google AI Studio (Gemini API) — تخضع لشروط وسياسات Google APIs.</li>
              <li>OpenAI — تخضع لسياسات وشروط OpenAI API.</li>
              <li>Anthropic — تخضع لشروط وسياسات Anthropic Commercial Terms.</li>
              <li>OpenRouter — تخضع لشروط خصوصية وسياسات OpenRouter.</li>
            </ul>
            <p style={{ margin: '8px 0 0 0' }}>
              <strong>تنويه الفوترة:</strong> منصة أساس لا تتقاضى أي مبالغ مالية مقابل المكالمات، ولا تدفع للمزودين، ولا تطلع على تفاصيل بطاقاتك الائتمانية أو حسابات الفوترة الخاصة بك لدى أي مزود.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>5. الإحصائيات المجهولة واحترام معايير الخصوصية</h2>
            <p style={{ margin: 0 }}>
              تجمع المنصة عدادات إحصائية مجهولة تماماً (مثل إجمالي عدد مرات استعراض الوكلاء وعدد التجارب الناجحة) وفقاً للمحددات الآتية:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li>لا تُستخدم أي ملفات تعريف ارتباط (Zero Cookies) للتتبع.</li>
              <li>لا يتم تسجيل عناوين IP أو معلومات المتصفح في سجلات التحليلات.</li>
              <li>نحترم خيارات المتصفح للخصوصية: إذا قمت بتفعيل خاصية عدم التتبع <code>Do-Not-Track (DNT: 1)</code> أو التحكم العالمي في الخصوصية <code>Global Privacy Control (Sec-GPC)</code>، يتم إيقاف تسجيل العدادات المجهولة لزيارتك بالكامل.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>6. التواصل والاستفسارات</h2>
            <p style={{ margin: 0 }}>
              لأي استفسارات تقنية أو أمنية حول المنصة، يسعدنا تواصلكم مع فريق الأمان في أساس AI عبر البريد الإلكتروني المعتمد: <code>security@asaas.ai</code>.
            </p>
          </section>
        </div>
      </Card>
    </div>
  );
}
