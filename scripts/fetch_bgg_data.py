# app/scripts/fetch_bgg_data.py

import sys
import os
import requests
import xml.etree.ElementTree as ET

# Allow imports to work correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import create_app
from app.models import db, Game

def fetch_game_details(bgg_id):
    """Fetch game details from BoardGameGeek API."""
    url = f"https://boardgamegeek.com/xmlapi2/thing?id={bgg_id}"
    response = requests.get(url)
    if response.status_code == 200:
        return response.content
    return None

def parse_game_details(xml_data):
    """Parse game details from the XML response."""
    root = ET.fromstring(xml_data)
    game_data = {}
    for item in root.findall('item'):
        game_data['name'] = item.find('name').attrib.get('value')
        game_data['description'] = item.find('description').text
        game_data['min_players'] = int(item.find('minplayers').attrib.get('value', 0))
        game_data['max_players'] = int(item.find('maxplayers').attrib.get('value', 0))
        game_data['playtime'] = int(item.find('playingtime').attrib.get('value', 0))
        game_data['image_url'] = item.find('image').text if item.find('image') is not None else None
    return game_data

def update_games():
    """Fetch and update game details in the database."""
    app = create_app()

    with app.app_context():
        games = Game.query.filter(Game.bgg_id.isnot(None)).all()
        for game in games:
            xml_data = fetch_game_details(game.bgg_id)
            if xml_data:
                try:
                    details = parse_game_details(xml_data)
                    game.name = details.get('name', game.name)
                    game.description = details.get('description', game.description)
                    game.min_players = details.get('min_players', game.min_players)
                    game.max_players = details.get('max_players', game.max_players)
                    game.playtime = details.get('playtime', game.playtime)
                    game.image_url = details.get('image_url', game.image_url)
                    db.session.commit()
                    print(f"Updated game: {game.name}")
                except Exception as e:
                    print(f"Error updating game with BGG ID {game.bgg_id}: {e}")

if __name__ == "__main__":
    update_games()
