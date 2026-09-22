import time
import threading

# После 429 RPM ключа снижается, а за каждый такой период без нового 429
# возвращается на один запрос в минуту, но не выше заданного. Без возврата ключ
# за долгую сессию съезжал 5→4→3→2→1 и дальше работал впятеро медленнее, хотя
# минутный лимит сервиса давно отпустил.
RPM_RECOVERY_SECONDS = 120.0

class RPMLimiter:
    """
    Потокобезопасный класс для РАВНОМЕРНОГО контроля скорости запросов (RPM).
    Версия 2.0: Добавлены методы для сброса и принудительного ожидания.
    """
    def __init__(self, rpm_limit: int):
        if rpm_limit <= 0:
            # "Безлимитный" режим: interval = 0.0 позволяет использовать
            # боевые методы класса без лямбда-заглушек. При interval == 0.0
            # can_proceed() всегда True, а seconds_until_next_allowed()
            # всегда 0.0 (см. tests/test_rpm_limiter.py::test_no_limit_always_zero) —
            # ЗА ИСКЛЮЧЕНИЕМ случая, когда update_last_request_time(delay)
            # явно отодвинула last_request_time в будущее: тогда пауза,
            # запрошенная сервером (TEMPORARY_LIMIT/NETWORK), по-прежнему
            # соблюдается, а не молча теряется, как было при лямбда-заглушках.
            self.rpm_limit = 0
            self.configured_rpm = 0
            self.interval = 0.0
            self.lock = threading.Lock()
            self.last_request_time = 0
            self._lowered_at = None
            return

        self.rpm_limit = rpm_limit
        self.configured_rpm = rpm_limit
        self.interval = 60.0 / self.rpm_limit
        self.lock = threading.Lock()
        self.last_request_time = 0
        self._lowered_at = None

    def can_proceed(self) -> bool:

        with self.lock:
            now = time.time()
            self._recover_unlocked(now)
            elapsed = now - self.last_request_time
            if elapsed >= self.interval:
                self.last_request_time = now
                return True
            return False

    def seconds_until_next_allowed(self) -> float:
        """Сколько секунд осталось до следующего разрешённого запроса.

        Возвращает 0.0, если запрос можно сделать прямо сейчас. Позволяет
        воркеру спать ровно до момента снятия RPM-лимита, а не будиться
        периодически вхолостую."""
        with self.lock:
            now = time.time()
            self._recover_unlocked(now)
            remaining = self.interval - (now - self.last_request_time)
            return remaining if remaining > 0 else 0.0

    def take_slot(self):
        """Занимает слот под запрос, который воркер уже решил отправить.

        Пара к seconds_until_next_allowed(): воркер сначала смотрит, свободен
        ли слот, и занимает его, только когда действительно взял задачу.
        Пустой опрос очереди слота не тратит."""
        with self.lock:
            self.last_request_time = time.time()

    # --- НАЧАЛО НОВЫХ МЕТОДОВ ---
    def reset(self):
        """
        Обнуляет таймер. Следующий вызов can_proceed() гарантированно пройдет.
        """
        with self.lock:
            self.last_request_time = 0
    
    def get_rpm(self) -> int:
        """Возвращает текущее значение RPM."""
        with self.lock:
            self._recover_unlocked(time.time())
            return self.rpm_limit
    
    def decrease_rpm(self, percentage=25):
        """
        Динамически снижает RPM лимит на заданный процент, но не ниже 1.
        Пересчитывает интервал.
        """
        with self.lock:
            if self.rpm_limit <= 0:
                # "Безлимитный" режим (см. __init__) — снижать нечего,
                # иначе get_rpm() начнёт врать (rpm_limit=1), а реального
                # троттлинга всё равно не появится: can_proceed() по-прежнему
                # руководствуется interval == 0.0.
                return
            now = time.time()
            self._recover_unlocked(now)
            # Считаем, на сколько нужно уменьшить
            reduction = int(self.rpm_limit * (percentage / 100.0))
            # Уменьшаем, но гарантируем, что останется хотя бы 1
            self.rpm_limit = max(1, self.rpm_limit - max(1, reduction)) # Уменьшаем минимум на 1
            self.interval = 60.0 / self.rpm_limit
            self._lowered_at = now

    def _recover_unlocked(self, now):
        """Возвращает по одному RPM за каждый спокойный период после снижения."""
        if self._lowered_at is None or self.rpm_limit >= self.configured_rpm:
            return
        steps = int((now - self._lowered_at) // RPM_RECOVERY_SECONDS)
        if steps <= 0:
            return
        self.rpm_limit = min(self.configured_rpm, self.rpm_limit + steps)
        self.interval = 60.0 / self.rpm_limit
        if self.rpm_limit >= self.configured_rpm:
            self._lowered_at = None
        else:
            self._lowered_at += steps * RPM_RECOVERY_SECONDS
    
    def update_last_request_time(self, delay=0):
        """
        Устанавливает "точку отсчета" так, чтобы следующий запрос
        был разрешен ровно через `delay` секунд, не добавляя
        дополнительного интервала RPM.
        """
        with self.lock:
            # T_next = Момент в будущем, когда мы хотим разрешить следующий запрос
            next_allowed_time = time.time() + delay
            
            # T_last_request = T_next - I
            # "Обманываем" лимитер, говоря ему, что последний запрос был сделан
            # ровно `interval` секунд назад от желаемого времени следующего запуска.
            self.last_request_time = next_allowed_time - self.interval
