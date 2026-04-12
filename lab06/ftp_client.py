#!/usr/bin/env python3

import argparse
import ftplib
import getpass
import sys
from pathlib import Path


def connect(host: str, port: int, user: str, password: str) -> ftplib.FTP:
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=60)
    ftp.login(user, password)
    return ftp


def cmd_list(ftp: ftplib.FTP) -> None:
    try:
        for name, facts in ftp.mlsd():
            if name in (".", ".."):
                continue
            kind = facts.get("type", "?")
            print(f"{kind}\t{name}")
    except ftplib.error_perm:
        lines: list[str] = []

        def collect(line: str) -> None:
            lines.append(line)

        ftp.retrlines("LIST", collect)
        for line in lines:
            print(line)


def cmd_upload(ftp: ftplib.FTP, local_path: str, remote_name: str) -> None:
    path = Path(local_path)
    if not path.is_file():
        raise SystemExit(f"Локальный файл не найден: {path}")
    with path.open("rb") as f:
        ftp.storbinary(f"STOR {remote_name}", f)
    print(f"Загружено: {path} -> {remote_name}")


def cmd_download(ftp: ftplib.FTP, remote_name: str, local_path: str) -> None:
    out = Path(local_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        ftp.retrbinary(f"RETR {remote_name}", f.write)
    print(f"Скачано: {remote_name} -> {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FTP-клиент (ftplib)")
    p.add_argument("-H", "--host", default="127.0.0.1", help="Хост FTP")
    p.add_argument("-P", "--port", type=int, default=21, help="Порт (по умолчанию 21)")
    p.add_argument("-u", "--user", required=True, help="Логин")
    p.add_argument(
        "-p",
        "--password",
        default=None,
        help="Пароль (если не указан — запрос ввода)",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Список файлов и каталогов в текущей папке на сервере")

    up = sub.add_parser("upload", help="Загрузить локальный файл на сервер")
    up.add_argument("local", help="Путь к локальному файлу")
    up.add_argument("remote", help="Имя файла на сервере")

    down = sub.add_parser("download", help="Скачать файл с сервера")
    down.add_argument("remote", help="Имя файла на сервере")
    down.add_argument("local", help="Куда сохранить локально")

    return p


def main() -> None:
    args = build_parser().parse_args()
    password = args.password
    if password is None:
        password = getpass.getpass("Пароль: ")

    try:
        ftp = connect(args.host, args.port, args.user, password)
    except Exception as e:
        raise SystemExit(f"Ошибка подключения: {e}") from e

    try:
        if args.command == "list":
            cmd_list(ftp)
        elif args.command == "upload":
            cmd_upload(ftp, args.local, args.remote)
        elif args.command == "download":
            cmd_download(ftp, args.remote, args.local)
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


if __name__ == "__main__":
    main()
