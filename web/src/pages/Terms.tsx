/**
 * DRAFT — مسودة شروط الاستخدام
 * تهميش هام: هذه الوثيقة مسودة تقنية خاضعة للمراجعة والاعتماد القانوني من قبل إدارة أساس AI قبل الإطلاق الرسمي.
 * لا تمثل هذه الصفحة استشارة قانونية.
 */
import { Card, Icon, Swash } from '../asaas-ui';
import { usePageMeta } from '../lib/usePageMeta';

export default function Terms() {
  usePageMeta({
    title: 'شروط الاستخدام — وكلاء أساس',
    description: 'شروط وأحكام استخدام منصة استعراض وكلاء أساس (ASAAS Agents Platform).',
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
          <strong>مسودة للمراجعة القانونية:</strong> تم إعداد هذه الوثيقة لتوثيق الشروط التقنية الخاصة بالمنصة، وهي خاضعة للمراجعة والاعتماد من قبل الإدارة القانونية لشركة أساس AI قبل النشر الرسمي.
        </span>
      </div>

      <Card style={{ padding: '28px' }}>
        <h1 className="title" style={{ margin: '0 0 8px 0', fontSize: '26px' }}>
          شروط وأحكام الاستخدام
          <Swash>.</Swash>
        </h1>
        <p className="subtle" style={{ margin: '0 0 24px 0', fontSize: '14px' }}>
          آخر تحديث تقني: نوفمبر 2026 | الإصدار 1.0 (مرشح للإطلاق)
        </p>

        <div className="prose" style={{ lineHeight: 1.8, color: 'var(--text-1)', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>1. طبيعة المنصة والغرض منها</h2>
            <p style={{ margin: 0 }}>
              منصة <strong>وكلاء أساس (ASAAS Agents Platform)</strong> هي منصة عرض تقني واستعراض عام (Public Showcase) للوكلاء الذكيين المطورين من قبل فريق هندسة الذكاء الاصطناعي في شركة <strong>أساس AI</strong>. تهدف المنصة إلى إبراز الإمكانات البرمجية وهيكليات الوكلاء المتقدمة، وهي ليست أداة لبناء الوكلاء (Agent Builder) ولا تتيح للمستخدمين رفع أو إنشاء وكلاء جدد عبر الواجهة.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>2. نموذج المفتاح الخاص والتكاليف (BYOK)</h2>
            <p style={{ margin: 0 }}>
              تعمل كافة التجارب الحية بناءً على مبدأ <em>"استخدم مفتاحك الخاص" (Bring Your Own Key)</em>:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li>يتحمل الزائر وحده المسؤولية الكاملة عن الحصول على مفتاح API من المزود المعتمد وإدارته وتكاليف استخدامه أو استهلاك حصصه المجانية والمدفوعة.</li>
              <li>لا تقدم أساس AI أي مفاتيح تجارية، ولا تتحمل أي تكاليف ناتجة عن استدعاء النماذج أثناء تجربتك لأي وكيل.</li>
              <li>الزائر مسؤول عن الحفاظ على سرية مفاتيحه وعدم مشاركتها مع أطراف غير موثوقة.</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>3. حدود الاستخدام المقبول (Acceptable Use Policy)</h2>
            <p style={{ margin: 0 }}>
              يوافق الزائر عند استخدام المنصة على الامتثال للقواعد الآتية:
            </p>
            <ul style={{ paddingInlineStart: '20px', margin: '8px 0' }}>
              <li>عدم استخدام الوكلاء لتوليد محتوى ضار، احتيالي، مسيء، ينتهك حقوق الآخرين، أو يخالف القوانين والأنظمة المعمول بها.</li>
              <li><strong>صلاحية فحص وزحف المواقع والموافقة الصريحة:</strong> عند استخدام وكلاء فحص وتحليل المواقع الإلكترونية (مثل Site DNA)، يتطلب النظام تأكيداً صريحاً قبل كل جولة بأن الموقع المدخل موقع عام يملك المستخدم صلاحية فحصه أو يطلب تحليله للاستخدام الشخصي/البحثي. ويُحظر تماماً محاولة فحص عناوين IP مباشرة أو شبكات خاصة أو خدمات داخلية أو استغلال الوكيل في أي مسح أمني غير مصرح به. كما يقر المستخدم بأن تفعيل خيار «استخبارات المنافسين» يؤدي إلى جلب صفحات عامة لمواقع منافسة، وأن جميع نتائج الجولات تُحذف تلقائياً بعد 60 دقيقة من الانتهاء.</li>
              <li>عدم محاولة كسر عزل البيئة الافتراضية (Sandbox Escape) أو الوصول إلى ملفات الخادم أو الشبكة الداخلية للمنصة.</li>
              <li>عدم إغراق الخوادم بالطلبات الآلية المكثفة (DDoS/Flooding) أو تجاوز حدود الاستخدام والتحقق المحددة في النظام.</li>
              <li>الالتزام التام بسياسات الاستخدام المقبول الخاصة بمزود النموذج المختار (Google, OpenAI, Anthropic, OpenRouter).</li>
            </ul>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>4. الملكية الفكرية والكود المصدري</h2>
            <p style={{ margin: 0 }}>
              كافة العلامات التجارية، والشعارات، والتصاميم البصرية (Liquid Glass Design System)، ومكتبة مكونات أساس، وهيكلية المنصة هي ملكية فكرية حصرية لشركة <strong>أساس AI</strong>. الأكواد المصدرية للوكلاء المعروضة ترتبط بمستودعات رسمية على GitHub وتخضع لرخص المصدر المفتوح المحددة في كل مستودع.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>5. إخلاء المسؤولية وحدود الضمان</h2>
            <p style={{ margin: 0 }}>
              يتم توفير المنصة وتجارب الوكلاء الحية على أساس <em>"كما هي" (AS IS)</em> و <em>"حسب التوفر"</em> لأغراض الاستعراض والاختبار التجريبي فقط، دون أي ضمانات صريحة أو ضمنية تشمل دقة النتائج، استمرارية الخدمة، أو ملاءمة مخرجات الوكلاء لقرارات الأعمال الحساسة دون مراجعة بشرية.
            </p>
          </section>

          <section>
            <h2 style={{ fontSize: '18px', margin: '0 0 8px 0', color: 'var(--accent)' }}>6. القانون المعتمد والتعديلات</h2>
            <p style={{ margin: 0 }}>
              تحتفظ أساس AI بالحق في تحديث وتعديل هذه الشروط في أي وقت لمواكبة التحديثات التقنية أو التنظيمية، وتسري أي تعديلات فور نشرها على هذه الصفحة.
            </p>
          </section>
        </div>
      </Card>
    </div>
  );
}
