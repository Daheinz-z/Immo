def score_listing(item, config=None):
    # config: weightings
    if config is None:
        config = {
            'w_price_m2': 0.30,
            'w_rent_yield': 0.30,
            'w_distance': 0.15,
            'w_condition': 0.15,
            'w_usage': 0.10,
        }
    score_components = {}
    # simple proxies
    price_m2 = None
    if item.get('price_eur') and item.get('living_m2'):
        try:
            price_m2 = item['price_eur'] / item['living_m2']
        except Exception:
            price_m2 = None

    # price score: lower price/m2 is better. We normalize using expected range.
    if price_m2:
        # assume reasonable bounds: 500 - 8000 EUR/m2
        p = max(500, min(8000, price_m2))
        score_components['price_m2'] = (8000 - p) / (8000 - 500) * 100
    else:
        score_components['price_m2'] = 50

    # rent yield: unknown -> neutral 50
    score_components['rent_yield'] = 50

    # distance: unknown -> neutral
    score_components['distance'] = 50

    # condition: unknown -> neutral
    score_components['condition'] = 50

    # usage: if text contains 'ferien' or 'urlaub' boost
    txt = (item.get('raw_text') or '').lower()
    usage = 50
    if 'ferien' in txt or 'urlaub' in txt or 'wochenend' in txt:
        usage = 80
    score_components['usage'] = usage

    final = (
        config['w_price_m2'] * score_components['price_m2'] +
        config['w_rent_yield'] * score_components['rent_yield'] +
        config['w_distance'] * score_components['distance'] +
        config['w_condition'] * score_components['condition'] +
        config['w_usage'] * score_components['usage']
    )
    item['score'] = round(final,1)
    item['score_components'] = score_components
    return item
