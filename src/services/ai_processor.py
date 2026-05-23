import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

# Завантажуємо змінні з .env файлу
load_dotenv()

class AIProcessor:
    def __init__(self):
        # Безпечно дістаємо ключ з середовища
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("❌ OPENAI_API_KEY не знайдено у файлі .env")

        # Ініціалізація асинхронного клієнта
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = "gpt-4o-mini" # Наша дешева та швидка модель

    async def test_connection(self) -> str:
        """Метод для виконання Definition of Done (відправка 'Hello')"""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": "Hello"}
                ],
                # ЛІМІТ ВИТРАТ: жорстко обмежуємо довжину відповіді до 20 токенів
                max_tokens=20,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"❌ Помилка API: {e}"

    async def analyze_lead_data(self, name: str, website: str, cms_type: str, reviews: str) -> dict:
            """
            Відправляє дані ліда до ШІ та повертає JSON з об'єктивною оцінкою.
            """
            if not self.client:
                print("❌ OpenAI API Key не налаштовано!")
                return {}

            print(f"   [DEBUG] Вхідні дані -> Сайт: '{website}' | CMS: '{cms_type}'")

            # 🛑 ХАК ДЛЯ СОЦМЕРЕЖ: Перехоплюємо інстаграм/фейсбук
            if website and any(social in website.lower() for social in ['instagram.com', 'facebook.com', 't.me', 'tiktok.com', 'linktr.ee', 'ig.me']):
                cms_type = "САЙТУ НЕМАЄ (Тільки соцмережа)"

            prompt = f"""
                    Ти експерт з оцінки b2b-лідів для веб-студії.
                    Поверни результат ВИКЛЮЧНО у форматі JSON.

                    Вхідні дані:
                    - Назва: {name}
                    - Сайт: {website or 'Немає сайту'}
                    - CMS: {cms_type or 'Невідомо'}
                    - Відгуки: {reviews or 'Немає відгуків'}

                    ГОЛОВНА ШКАЛА ОЦІНКИ (lead_score від 0 до 10).
                    Жорстко дотримуйся цієї логіки:

                    1. Немає сайту (або вказана лише соцмережа) + Хороші відгуки = 10.
                    2. Немає сайту + Погані відгуки = 9.
                    3. Сайт на конструкторі (Tilda, Wix) + Погані відгуки = 8.
                    4. Сайт на конструкторі (Tilda, Wix) + Хороші відгуки = 5.
                    5. Повноцінний сайт (не конструктор) + Погані відгуки = 7.
                    6. Повноцінний сайт (React, Vue, кастом) + Хороші відгуки = 0. (Не чіпаємо, послуги не пропонуємо!).

                    Правило для clean_name:
                    Очисти назву від форм власності (ТОВ, ФОП, ПП) та зайвих символів.

                    Формат JSON, який ти маєш повернути.
                    ВАЖЛИВО: поле 'reasoning' має йти ПЕРШИМ, щоб ти спочатку проаналізував правило, а вже потім ставив число!

                    Приклад ідеальної відповіді для сайту на React з хорошими відгуками:
                    {{
                        "clean_name": "Очищена назва",
                        "reasoning": "Я бачу повноцінний сайт на React та позитивні відгуки. Відповідно до правила №6, цей бізнес не потребує наших послуг, тому оцінка строго 0.",
                        "lead_score": 0,
                        "ai_summary": "У компанії є сучасний сайт і немає скарг на сервіс — клієнт нам не цікавий."
                    }}
                    """

            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    response_format={"type": "json_object"},
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=300,
                    temperature=0.1 # Мінімальна температура для об'єктивності та строгого слідування правилам
                )
                return json.loads(response.choices[0].message.content)
            except Exception as e:
                print(f"Помилка під час аналізу ШІ: {e}")
                return {"clean_name": name, "lead_score": 0, "ai_summary": "Помилка аналізу"}

    async def generate_cold_intro(
        self,
        clean_name: str,
        cms_type: str,
        reviews: str,
        ai_summary: str,
        rating: str | None = None,
        reviews_count: str | None = None,
        category: str | None = None,
        language: str = "Ukrainian",
    ) -> str:
        """
        Generate a short, personalized ice-breaker message for a cold email.
        """
        # Map cms_type → website_status for the prompt
        if not cms_type or cms_type in ("No Website", "Social Media"):
            website_status = "None"
        elif cms_type in ("Tilda", "Wix"):
            website_status = "Tilda/Wix"
        else:
            website_status = "Exists"

        # Build language-specific examples so the LLM follows the right language
        if language == "Ukrainian":
            examples = """
Scenario 1 (High rating, NO WEBSITE):
"Доброго дня, команда Secret Garden! Бачу, у вас майже ідеальний рейтинг (4.9), клієнти в захваті. Але як вони можуть побачити ваші букети онлайн, якщо у вас немає сайту-вітрини? Гадаю, ви втрачаєте частину замовлень."

Scenario 2 (Tilda/Wix website):
"Вітаю! Помітив ваш салон "Nails & Beauty". Чудово, що у вас є сайт, але перевірив з мобільного — він завантажується трохи повільно, що типово для конструкторів. Це може відлякувати клієнтів, які шукають манікюр "на ходу". Цікаво було б це виправити?"

Scenario 3 (Specific complaint in reviews):
"Доброго дня! Клієнти дуже хвалять вашу "Kvitkova Kava", але я помітив у відгуках, що людям не вистачає онлайн-прайсу. Простий сайт з цінами міг би значно розвантажити ваші телефони. Як вам така ідея?"

Scenario 4 (Low rating or few reviews):
"Вітаю, команда "Style Zone"! Бачу, ви нещодавно відкрились і ще набираєте клієнтську базу. Професійний сайт міг би одразу заявити про вас як про топ-барбершоп і швидше залучити перших постійних клієнтів. Цікаво було б обговорити?"
"""
        elif language == "Polish":
            examples = """
Scenario 1 (High rating, NO WEBSITE):
"Dzień dobry, zespół Secret Garden! Widzę, że macie prawie idealną ocenę (4.9), klienci są zachwyceni. Ale jak mogą zobaczyć Wasze bukiety online, skoro nie macie strony internetowej? Myślę, że tracicie część zamówień."

Scenario 2 (Tilda/Wix website):
"Cześć! Zauważyłem Wasz salon "Nails & Beauty". Super, że macie stronę, ale sprawdziłem na telefonie — ładuje się dość wolno, co jest typowe dla kreatorów stron. To może zniechęcać klientów szukających manicure "w biegu". Chcielibyście to poprawić?"

Scenario 3 (Specific complaint in reviews):
"Dzień dobry! Klienci bardzo chwalą "Kvitkova Kava", ale zauważyłem w opiniach, że brakuje cennika online. Prosta strona z cenami mogłaby znacznie odciążyć Wasze telefony. Co myślicie?"

Scenario 4 (Low rating or few reviews):
"Cześć, zespół "Style Zone"! Widzę, że niedawno się otworzyliście i dopiero budujecie bazę klientów. Profesjonalna strona mogłaby od razu zaprezentować Was jako top-barbershop. Chcielibyście o tym porozmawiać?"
"""
        else:  # English and all other languages
            examples = """
Scenario 1 (High rating, NO WEBSITE):
"Hi, Secret Garden team! I see you've got an amazing 4.9 rating — customers love you. But how can they see your bouquets online if you don't have a website? I think you might be missing out on orders."

Scenario 2 (Tilda/Wix website):
"Hey there! I came across your salon "Nails & Beauty". Great that you have a website, but I checked it on mobile — it loads a bit slow, which is typical for website builders. That might turn away clients looking for a quick manicure. Interested in fixing that?"

Scenario 3 (Specific complaint in reviews):
"Hi! Customers really love "Kvitkova Kava", but I noticed in reviews that people wish there was an online price list. A simple website with prices could take a lot of pressure off your phones. What do you think?"

Scenario 4 (Low rating or few reviews):
"Hey, Style Zone team! I see you've recently opened and are still building your client base. A professional website could instantly position you as a top barbershop and attract your first loyal customers faster. Would you like to discuss this?"
"""

        prompt = f"""Act as a friendly and sharp-eyed business development consultant for a web studio.
Generate ONE compelling opening message (2-3 sentences).

CRITICAL: You MUST write the message in **{language}**. Do NOT use any other language.

**Input Data:**
- business_name: {clean_name}
- category: {category or 'Unknown'}
- rating: {rating or 'Unknown'}
- reviews_count: {reviews_count or 'Unknown'}
- website_status: {website_status}
- review_snippet: {reviews or 'No reviews'}

**Instructions & Tone:**
- Be Specific: Use the business_name and category.
- Sound Human: Friendly, slightly informal but professional.
- Focus on a Single Pain Point based on the data.
- Soft Call to Action: End with an open question.
- Do NOT invent facts that are not in the data.

**Examples (in {language}):**
{examples}
Now generate ONE message in **{language}**. Return ONLY the message text, no quotes, no explanations."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            return f"[Помилка генерації: {e}]"

# Блок для швидкого локального тестування файлу
if __name__ == "__main__":
    async def run_test():
        ai = AIProcessor()

        print("🤖 Тест 1: З'єднання (Definition of Done)...")
        answer = await ai.test_connection()
        print(f"Відповідь: {answer}\n")

        print("🤖 Тест 2: Аналіз тестового ліда...")
        test_analysis = await ai.analyze_lead_data(
            name="ФОП Ромашка Київ",
            website="https://romashka.tilda.ws",
            cms_type="Tilda",
            reviews="Квіти гарні, але доставка запізнилася на 2 години. Додзвонитися неможливо!"
        )
        print("Результат аналізу:")
        print(json.dumps(test_analysis, indent=4, ensure_ascii=False))

    asyncio.run(run_test())