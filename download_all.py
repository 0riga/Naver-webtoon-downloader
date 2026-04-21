#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Парсер и скачивание всех глав тайтла

Поддерживаемые форматы ссылок:
- https://comic.naver.com/webtoon/list?titleId=812354
- https://comic.naver.com/webtoon/detail?titleId=812354&no=18&week=thu
- https://comic.naver.com/webtoon/list?titleId=812354&page=12&sort=DESC&tab=thu
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import time
import os
import requests
import re


def extract_title_id(url):
    """
    Извлекает titleId из любой ссылки Naver Comic
    
    Args:
        url: Любая ссылка (list или detail)
    
    Returns:
        str: titleId или None
    """
    match = re.search(r'titleId=(\d+)', url)
    if match:
        return match.group(1)
    return None


def normalize_url(url):
    """
    Конвертирует любую ссылку в базовый формат списка
    
    Args:
        url: Любая ссылка Naver Comic
    
    Returns:
        str: Базовый URL списка без page, sort, tab параметров
    """
    # Извлекаем titleId
    title_id = extract_title_id(url)
    if not title_id:
        print(f"[ERROR] Не удалось извлечь titleId из URL: {url}")
        return None
    
    # Формируем базовый URL
    base_url = f"https://comic.naver.com/webtoon/list?titleId={title_id}"
    return base_url


def setup_driver():
    """Настройка headless Chrome драйвера"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = webdriver.Chrome(options=options)
    return driver


def get_all_episodes(base_url, timeout=30):
    """
    Получает все эпизоды из тайтла
    
    Args:
        base_url: Базовый URL списка
        timeout: таймаут ожидания
    
    Returns:
        list: Список всех эпизодов с title и url
    """
    driver = None
    all_episodes = []
    all_episode_urls = set()
    current_page = 0
    
    try:
        print(f"\n[INFO] Открываю страницу: {base_url}")
        driver = setup_driver()
        
        while True:
            current_page += 1
            print(f"\n[INFO] ===== Страница {current_page} =====")
            
            # Формируем URL страницы
            if current_page == 1:
                url = base_url
            else:
                url = f"{base_url}&page={current_page}"
            
            driver.get(url)
            
            # Ждём загрузки списка эпизодов
            try:
                wait = WebDriverWait(driver, timeout)
                wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, 'ul.EpisodeListList__episode_list--_N3ks')
                    )
                )
            except TimeoutException:
                if current_page == 1:
                    print(f"[ERROR] Не удалось загрузить первую страницу")
                    return []
                else:
                    print(f"[INFO] Достигли конца пагинации")
                    break
            
            # Получаем все элементы списка
            items = driver.find_elements(By.CSS_SELECTOR, 'li.EpisodeListList__item--M8zq4')
            
            if not items:
                print(f"[INFO] Нет элементов на странице {current_page}")
                break
            
            # Добавляем эпизоды
            page_episodes = []
            for item in items:
                try:
                    link_elem = item.find_element(By.TAG_NAME, 'a')
                    link = link_elem.get_attribute('href')
                    title_elem = link_elem.find_element(By.CSS_SELECTOR, 'span, strong')
                    title = title_elem.text.strip() if title_elem else "Без названия"
                    title = title.split('\n')[0].strip()
                    
                    if not link:
                        continue
                    
                    # Проверка дубликатов МЕЖДУ страницами
                    if link in all_episode_urls:
                        print(f"[INFO] Обнаружен дубликат - конец пагинации")
                        break
                    
                    all_episode_urls.add(link)
                    episode = {'title': title, 'url': link}
                    page_episodes.append(episode)
                    all_episodes.append(episode)
                        
                except Exception as e:
                    continue
            
            print(f"[OK] Страница {current_page}: {len(page_episodes)} эпизодов (всего: {len(all_episodes)})")
            
            # Если меньше 20 эпизодов - последняя страница
            if len(page_episodes) < 20:
                print(f"[INFO] Последняя страница ({len(page_episodes)} эпизодов)")
                break
            
            time.sleep(1)
        
        return all_episodes
        
    except Exception as e:
        print(f"[ERROR] {type(e).__name__}: {e}")
        return []
        
    finally:
        if driver:
            driver.quit()
            print(f"[INFO] Браузер закрыт")


def get_chapter_number_from_url(chapter_url):
    """
    Извлекает номер главы из URL
    
    Args:
        chapter_url: URL главы (detail)
    
    Returns:
        int: Номер главы или 0
    """
    match = re.search(r'&no=(\d+)', chapter_url)
    if match:
        return int(match.group(1))
    return 0


def download_chapter_images(chapter_url, output_folder, chapter_title, timeout=30, max_retries=3):
    """
    Скачивает изображения из одной главы
    
    Args:
        chapter_url: URL главы
        output_folder: Папка для сохранения
        chapter_title: Название главы
        timeout: таймаут
        max_retries: макс. количество попыток
    
    Returns:
        dict: {'success': bool, 'count': int}
    """
    driver = None
    
    try:
        # Очищаем название для папки
        chapter_title_clean = re.sub(r'[<>:"/\\|?*]', '_', chapter_title)
        chapter_title_clean = chapter_title_clean[:50]
        chapter_folder = os.path.join(output_folder, chapter_title_clean)
        
        if not os.path.exists(chapter_folder):
            os.makedirs(chapter_folder)
        
        print(f"[INFO] Открываю главу: {chapter_title}")
        driver = setup_driver()
        driver.get(chapter_url)
        time.sleep(2)
        
        # Получаем изображения
        images = driver.find_elements(By.CSS_SELECTOR, 'div.wt_viewer img')
        
        if not images:
            print(f"[WARN] Нет изображений в главе")
            return {'success': False, 'count': 0}
        
        downloaded_count = 0
        
        for i, img in enumerate(images):
            try:
                img_url = img.get_attribute('src')
                if not img_url:
                    continue
                
                img_filename = f'image_{i+1:04d}.jpg'
                img_path = os.path.join(chapter_folder, img_filename)
                
                # Пробуем скачать с повторами
                success = False
                for retry in range(max_retries):
                    try:
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        response = requests.get(img_url, headers=headers, timeout=timeout)
                        
                        if response.status_code == 200:
                            with open(img_path, 'wb') as f:
                                f.write(response.content)
                            downloaded_count += 1
                            success = True
                            break
                        else:
                            time.sleep(1 * (retry + 1))  # Задержка перед повтором
                    except requests.exceptions.Timeout:
                        if retry < max_retries - 1:
                            print(f"  [RETRY] {i+1}/{len(images)} - попытка {retry+2}")
                            time.sleep(2 * (retry + 1))
                        continue
                    except Exception:
                        break
                
                if not success:
                    print(f"  [FAIL] {i+1}/{len(images)}")
                
                time.sleep(0.05)  # Минимальная задержка между изображениями
                
            except Exception as e:
                continue
        
        print(f"[OK] {chapter_title[:40]}... - {downloaded_count}/{len(images)} изображений")
        
        return {'success': downloaded_count > 0, 'count': downloaded_count}
        
    except Exception as e:
        print(f"[ERROR] {chapter_title}: {e}")
        return {'success': False, 'count': 0}
        
    finally:
        if driver:
            driver.quit()


def download_all_chapters(base_url, start_chapter_name=None, start_chapter_no=None, start_chapter_url=None, output_folder='downloads', single_chapter=False):
    """
    Скачивает все главы от указанной до конца
    
    Args:
        base_url: Базовый URL тайтла
        start_chapter_name: Название начальной главы (частичное совпадение)
        start_chapter_no: Номер начальной главы (no= из URL)
        start_chapter_url: URL начальной главы
        output_folder: Папка для сохранения
        single_chapter: Скачать только одну главу (True) или все до конца (False)
    
    Returns:
        dict: Итоговая статистика
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    print("=" * 60)
    print("СКАЧИВАНИЕ ВСЕХ ГЛАВ")
    print("=" * 60)
    
    # Получаем все эпизоды
    print("\n[STEP 1] Получение списка всех глав...")
    all_episodes = get_all_episodes(base_url)
    
    if not all_episodes:
        print("[ERROR] Не удалось получить список глав")
        return {'success': False, 'total': 0, 'downloaded': 0}
    
    print(f"\n[RESULT] Найдено {len(all_episodes)} глав")
    
    # Определяем начальный индекс
    start_index = 0
    
    if start_chapter_name:
        # Ищем главу по названию (частичное совпадение)
        print(f"[INFO] Поиск главы по названию: '{start_chapter_name}'")
        
        for i, ep in enumerate(all_episodes):
            if start_chapter_name.lower() in ep['title'].lower():
                start_index = i
                print(f"[OK] Найдена глава: {ep['title']}")
                break
    
        if start_index == 0 and start_chapter_name.lower() not in all_episodes[0]['title'].lower():
            print(f"[ERROR] Глава с названием '{start_chapter_name}' не найдена")
            return {'success': False, 'total': 0, 'downloaded': 0}
    
    elif start_chapter_url:
        # Ищем главу по URL
        target_no = get_chapter_number_from_url(start_chapter_url)
        print(f"[INFO] Начальная глава (по URL): no={target_no}")
        
        for i, ep in enumerate(all_episodes):
            ep_no = get_chapter_number_from_url(ep['url'])
            if ep_no == target_no:
                start_index = i
                break
    
    elif start_chapter_no:
        # Ищем главу по номеру
        print(f"[INFO] Начальная глава (по номеру): no={start_chapter_no}")
        
        for i, ep in enumerate(all_episodes):
            ep_no = get_chapter_number_from_url(ep['url'])
            if ep_no == start_chapter_no:
                start_index = i
                break
    
    print(f"[INFO] Начинать с индекса {start_index} ({start_index + 1}-я глава)")
    
    # Скачиваем главы
    print("\n[STEP 2] Скачивание изображений...")
    total_downloaded = 0
    total_chapters = 0
    failed_chapters = []  # Список неудачных глав
    
    for i in range(start_index, len(all_episodes)):
        ep = all_episodes[i]
        chapter_num = i + 1
        ep_no = get_chapter_number_from_url(ep['url'])
        
        print(f"\n[{chapter_num}/{len(all_episodes)}] Глава {ep_no}: {ep['title'][:50]}...")
        
        result = download_chapter_images(
            ep['url'],
            output_folder,
            ep['title']
        )
        
        if result['success']:
            total_downloaded += result['count']
            total_chapters += 1
        else:
            print(f"[WARN] Не удалось скачать главу {ep['title'][:30]}...")
            failed_chapters.append(ep)  # Добавляем в список неудачных
        
        # Если нужно скачать только одну главу - выходим
        if single_chapter:
            print(f"[INFO] Скачана одна глава - завершение")
            break
        
        time.sleep(0.1)  # Минимальная задержка между главами
    
    # Повторная загрузка неудачных глав
    if failed_chapters:
        print("\n" + "=" * 60)
        print(f"[RETRY] Попытка повторной загрузки {len(failed_chapters)} глав...")
        print("=" * 60)
        
        for ep in failed_chapters:
            print(f"\n[RETRY] Глава: {ep['title'][:50]}...")
            result = download_chapter_images(
                ep['url'],
                output_folder,
                ep['title'],
                max_retries=5  # Больше попыток при повторе
            )
            
            if result['success']:
                total_downloaded += result['count']
                total_chapters += 1
                print(f"[OK] Успешно загружена при повторе!")
            else:
                print(f"[FAIL] Не удалось загрузить при повторе")
            
            time.sleep(0.5)  # Задержка между повторами
    
    print("\n" + "=" * 60)
    print(f"[RESULT] ИТОГИ:")
    print(f"  - Всего глав в тайтле: {len(all_episodes)}")
    print(f"  - Скачано глав: {total_chapters}")
    print(f"  - Всего изображений: {total_downloaded}")
    print(f"  - Папка: {output_folder}")
    if failed_chapters and len(failed_chapters) > 0:
        print(f"  - Не загружено (после повторов): {len([ep for ep in failed_chapters if True])}")
    print("=" * 60)
    
    return {
        'success': total_downloaded > 0,
        'total_episodes': len(all_episodes),
        'downloaded_chapters': total_chapters,
        'total_images': total_downloaded
    }


def main():
    """Основная функция CLI"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Скачивание всех глав вебтуана с Naver Comic',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  # Скачать ВСЕ главы:
  python download_all.py -u "https://comic.naver.com/webtoon/list?titleId=812354"
  
  # Скачать с конкретной главы по названию:
  python download_all.py -u "https://comic.naver.com/webtoon/list?titleId=812354" -n "드레스투어"
  
  # Скачать ТОЛЬКО ОДНУ главу по названию:
  python download_all.py -u "https://comic.naver.com/webtoon/list?titleId=812354" -n "어린이집" -1
  
  # Скачать с главы по номеру:
  python download_all.py -u "https://comic.naver.com/webtoon/list?titleId=812354" -s 18
  
  # Скачать с главы по URL:
  python download_all.py -u "https://comic.naver.com/webtoon/detail?titleId=812354&no=50&week=thu"
        """
    )
    
    parser.add_argument(
        '-u', '--url',
        required=True,
        help='URL тайтла (list или detail)'
    )
    
    parser.add_argument(
        '-n', '--name',
        dest='chapter_name',
        help='Название начальной главы (частичное совпадение)'
    )
    
    parser.add_argument(
        '-1', '--single',
        dest='single_chapter',
        action='store_true',
        help='Скачать только одну главу (вместе с -n, -s или -c)'
    )
    
    parser.add_argument(
        '-s', '--start-no',
        type=int,
        help='Номер начальной главы (no= из URL)'
    )
    
    parser.add_argument(
        '-c', '--start-chapter',
        help='URL начальной главы'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='downloads',
        help='Папка для сохранения (по умолчанию: downloads)'
    )
    
    args = parser.parse_args()
    
    # Проверяем, является ли URL ссылкой на главу (detail)
    is_detail_url = '/detail?' in args.url
    
    # Если URL главы и флаг -1, извлекаем номер главы
    start_no_from_url = None
    if is_detail_url and args.single_chapter:
        match = re.search(r'&no=(\d+)', args.url)
        if match:
            start_no_from_url = int(match.group(1))
            print(f"[INFO] Обнаружен URL главы: no={start_no_from_url}")
    
    # Нормализуем URL
    base_url = normalize_url(args.url)
    if not base_url:
        print(f"[ERROR] Неверный URL: {args.url}")
        return 1
    
    print(f"[INFO] Базовый URL: {base_url}")
    
    # Определяем параметры для скачивания
    chapter_name = args.chapter_name
    chapter_no = args.start_no or start_no_from_url
    chapter_url = args.start_chapter
    
    # Если только URL главы и -1, используем извлечённый номер
    if is_detail_url and args.single_chapter and not chapter_name and not args.start_chapter:
        chapter_no = start_no_from_url
    
    # Скачиваем главы
    result = download_all_chapters(
        base_url,
        start_chapter_name=chapter_name,
        start_chapter_url=chapter_url,
        start_chapter_no=chapter_no,
        output_folder=args.output,
        single_chapter=args.single_chapter
    )
    
    return 0 if result['success'] else 1


if __name__ == '__main__':
    sys.exit(main())
