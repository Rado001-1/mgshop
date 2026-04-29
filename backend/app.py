from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
import time, random, string, threading, os, math, re
from collections import Counter

from dotenv import load_dotenv
load_dotenv("secret.env")

app = Flask(__name__)
CORS(app, resources={r"/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})
# ================================================================
# CONFIG DATABASE — compatible local + Render
# ================================================================
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:MGShop2024@localhost:5432/mgshop'
)
# Render retourne parfois "postgres://" (ancien format), SQLAlchemy veut "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    
app.config['SQLALCHEMY_DATABASE_URI']        = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS']      = {
    'pool_pre_ping': True,      # vérifie la connexion avant chaque requête
    'pool_recycle':  280,       # recycle les connexions toutes les ~5 min (évite les timeouts Render)
    'pool_size':     5,
    'max_overflow':  2,
}
# ================================================================
# CONFIG MAIL
# ================================================================
app.config['MAIL_SERVER']         = 'smtp.gmail.com'
app.config['MAIL_PORT']           = 587
app.config['MAIL_USE_TLS']        = True
app.config['MAIL_USE_SSL']        = False
app.config['MAIL_USERNAME']       = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD']       = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = ('MGShop', os.getenv('MAIL_USERNAME'))

mail = Mail(app)
db   = SQLAlchemy(app)

# ================================================================
# STOP WORDS (FR + EN)
# ================================================================
STOP_WORDS = set([
    "le","la","les","de","du","des","un","une","et","en","à","au","aux",
    "ce","cet","cette","ces","mon","ma","mes","ton","ta","tes","son","sa",
    "ses","notre","votre","leur","leurs","par","pour","sur","sous","dans",
    "avec","sans","est","sont","avoir","être","mais","ou","ni","car","donc",
    "or","que","qui","quoi","dont","où","si","ne","pas","plus","très","bien",
    "peut","tout","tous","plus","même","comme","aussi","alors","après","avant",
    "the","a","an","and","or","but","in","on","at","to","for","of","with",
    "is","are","was","were","be","been","have","has","had","do","does","did",
    "not","no","so","if","as","by","from","that","this","it","he","she","we",
    "you","they","i","my","your","his","her","our","their","its","which","who",
])

# ================================================================
# MODELS
# ================================================================

class User(db.Model):
    __tablename__ = 'users'
    id            = db.Column(db.Integer, primary_key=True)
    nom           = db.Column(db.String(100), nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    mot_de_passe  = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20), default='user')
    date_creation = db.Column(db.DateTime, server_default=db.func.now())

class Shop(db.Model):
    __tablename__ = 'shops'
    id          = db.Column(db.Integer, primary_key=True)
    nom         = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    logo        = db.Column(db.Text)
    owner_id    = db.Column(db.Integer, db.ForeignKey('users.id'))
    valide      = db.Column(db.Boolean, default=False)

class Category(db.Model):
    __tablename__ = 'categories'
    id          = db.Column(db.Integer, primary_key=True)
    nom         = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)
    couleur     = db.Column(db.String(20), default='#6366f1')

class Product(db.Model):
    __tablename__ = 'products'
    id               = db.Column(db.Integer, primary_key=True)
    nom              = db.Column(db.String(100), nullable=False)
    description      = db.Column(db.Text)
    prix             = db.Column(db.Numeric(10, 2), nullable=False)
    prix_original    = db.Column(db.Numeric(10, 2), nullable=True)
    stock            = db.Column(db.Integer, default=0)
    stock_reserve    = db.Column(db.Integer, default=0)
    image            = db.Column(db.Text)
    shop_id          = db.Column(db.Integer, db.ForeignKey('shops.id'))
    category_id      = db.Column(db.Integer, db.ForeignKey('categories.id'))
    sku              = db.Column(db.String(50), unique=True)
    disponible       = db.Column(db.Boolean, default=True)
    promotion_active = db.Column(db.Boolean, default=False)
    tags_auto        = db.Column(db.Text, nullable=True)
    spam_score       = db.Column(db.Float, default=0.0)

class Badge(db.Model):
    __tablename__ = 'badges'
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'))
    nom        = db.Column(db.String(50), nullable=False)

class PickupLocation(db.Model):
    __tablename__ = 'pickup_locations'
    id       = db.Column(db.Integer, primary_key=True)
    nom      = db.Column(db.String(150), nullable=False)
    adresse  = db.Column(db.Text, nullable=False)
    horaires = db.Column(db.String(200))
    actif    = db.Column(db.Boolean, default=True)

class Order(db.Model):
    __tablename__ = 'orders'
    id                 = db.Column(db.Integer, primary_key=True)
    user_id            = db.Column(db.Integer, db.ForeignKey('users.id'))
    total              = db.Column(db.Numeric(10, 2), default=0)
    status             = db.Column(db.String(30), default='pending')
    payment_mode       = db.Column(db.String(50))
    payment_ref        = db.Column(db.String(200))
    pickup_location_id = db.Column(db.Integer, db.ForeignKey('pickup_locations.id'), nullable=True)
    date_creation      = db.Column(db.DateTime, server_default=db.func.now())
    date_pickup        = db.Column(db.DateTime, nullable=True)
    note_pickup        = db.Column(db.Text, nullable=True)

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id            = db.Column(db.Integer, primary_key=True)
    order_id      = db.Column(db.Integer, db.ForeignKey('orders.id'))
    product_id    = db.Column(db.Integer, db.ForeignKey('products.id'))
    quantity      = db.Column(db.Integer)
    prix_unitaire = db.Column(db.Numeric(10, 2))

class OTPCode(db.Model):
    __tablename__ = 'otp_codes'
    id         = db.Column(db.Integer, primary_key=True)
    email      = db.Column(db.String(150), nullable=False, index=True)
    code       = db.Column(db.String(100), nullable=False)
    type       = db.Column(db.String(20),  nullable=False)
    used       = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

class SpamModelStore(db.Model):
    __tablename__ = 'spam_model_store'
    id         = db.Column(db.Integer, primary_key=True)
    label      = db.Column(db.String(10), nullable=False)
    text       = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

# ================================================================
# NLP ENGINE
# ================================================================

class NLPEngine:
    @staticmethod
    def preprocess(text: str) -> list:
        if not text:
            return []
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\d+', ' ', text)
        tokens = text.split()
        tokens = [t for t in tokens if len(t) > 2 and t not in STOP_WORDS]
        return tokens

    @staticmethod
    def compute_tf(tokens: list) -> dict:
        if not tokens:
            return {}
        count = Counter(tokens)
        total = len(tokens)
        return {word: cnt / total for word, cnt in count.items()}

    @staticmethod
    def compute_idf(documents: list) -> dict:
        N = len(documents)
        if N == 0:
            return {}
        df = {}
        for doc in documents:
            unique_words = set(doc)
            for w in unique_words:
                df[w] = df.get(w, 0) + 1
        return {w: math.log((N + 1) / (df_w + 1)) + 1 for w, df_w in df.items()}

    @staticmethod
    def compute_tfidf(tokens: list, idf: dict) -> dict:
        tf = NLPEngine.compute_tf(tokens)
        return {w: tf_val * idf.get(w, 1.0) for w, tf_val in tf.items()}

    @staticmethod
    def vectorize(tfidf_dict: dict, vocab: list) -> list:
        return [tfidf_dict.get(w, 0.0) for w in vocab]

    @staticmethod
    def cosine_similarity(v1: list, v2: list) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        mag1 = math.sqrt(sum(a * a for a in v1))
        mag2 = math.sqrt(sum(b * b for b in v2))
        if mag1 == 0 or mag2 == 0:
            return 0.0
        return dot / (mag1 * mag2)

    @staticmethod
    def extract_tags(text: str, all_texts: list = None, n: int = 8) -> list:
        tokens = NLPEngine.preprocess(text)
        if not tokens:
            return []
        if all_texts and len(all_texts) > 1:
            corpus = [NLPEngine.preprocess(t) for t in all_texts]
        else:
            corpus = [tokens, tokens]
        idf = NLPEngine.compute_idf(corpus)
        tfidf = NLPEngine.compute_tfidf(tokens, idf)
        sorted_tags = sorted(tfidf.items(), key=lambda x: x[1], reverse=True)
        return [tag for tag, _ in sorted_tags[:n]]

    @staticmethod
    def text_stats(text: str, all_texts: list = None) -> dict:
        tokens = NLPEngine.preprocess(text)
        tf     = NLPEngine.compute_tf(tokens)
        corpus = [NLPEngine.preprocess(t) for t in (all_texts or [text])]
        idf    = NLPEngine.compute_idf(corpus)
        tfidf  = NLPEngine.compute_tfidf(tokens, idf)
        top_tfidf = sorted(tfidf.items(), key=lambda x: x[1], reverse=True)[:20]
        return {
            'word_count':   len(tokens),
            'unique_words': len(set(tokens)),
            'top_tf':       sorted(tf.items(), key=lambda x: x[1], reverse=True)[:10],
            'top_idf':      sorted(idf.items(), key=lambda x: x[1], reverse=True)[:10],
            'top_tfidf':    top_tfidf,
        }

    @staticmethod
    def similarity_matrix(texts: list) -> list:
        if not texts:
            return []
        corpus  = [NLPEngine.preprocess(t) for t in texts]
        idf     = NLPEngine.compute_idf(corpus)
        vocab   = list(idf.keys())
        vectors = []
        for tokens in corpus:
            tfidf  = NLPEngine.compute_tfidf(tokens, idf)
            vec    = NLPEngine.vectorize(tfidf, vocab)
            vectors.append(vec)
        n   = len(vectors)
        mat = [[0.0] * n for _ in range(n)]
        for i in range(n):
            for j in range(n):
                mat[i][j] = NLPEngine.cosine_similarity(vectors[i], vectors[j])
        return mat

    @staticmethod
    def train_naive_bayes(training_data: list) -> dict:
        spam_words = Counter()
        ham_words  = Counter()
        spam_total = 0
        ham_total  = 0
        spam_docs  = 0
        ham_docs   = 0
        for text, label in training_data:
            tokens = NLPEngine.preprocess(text)
            if label == 1:
                spam_words.update(tokens)
                spam_total += len(tokens)
                spam_docs  += 1
            else:
                ham_words.update(tokens)
                ham_total  += len(tokens)
                ham_docs   += 1
        total_docs = spam_docs + ham_docs
        if total_docs == 0:
            return {}
        vocab = set(list(spam_words.keys()) + list(ham_words.keys()))
        V     = len(vocab)
        return {
            'prior_spam': spam_docs / total_docs if total_docs else 0.5,
            'prior_ham':  ham_docs  / total_docs if total_docs else 0.5,
            'spam_words': dict(spam_words),
            'ham_words':  dict(ham_words),
            'spam_total': spam_total,
            'ham_total':  ham_total,
            'vocab_size': V,
        }

    @staticmethod
    def predict_spam(text: str, model: dict) -> dict:
        if not model:
            return {'label': 0, 'probability': 0.0, 'is_spam': False}
        tokens     = NLPEngine.preprocess(text)
        V          = model.get('vocab_size', 1)
        spam_total = model.get('spam_total', 1)
        ham_total  = model.get('ham_total', 1)
        spam_words = model.get('spam_words', {})
        ham_words  = model.get('ham_words', {})
        log_spam = math.log(model.get('prior_spam', 0.5) + 1e-10)
        log_ham  = math.log(model.get('prior_ham',  0.5) + 1e-10)
        for token in tokens:
            p_spam = (spam_words.get(token, 0) + 1) / (spam_total + V)
            p_ham  = (ham_words.get(token, 0)  + 1) / (ham_total  + V)
            log_spam += math.log(p_spam + 1e-10)
            log_ham  += math.log(p_ham  + 1e-10)
        max_log  = max(log_spam, log_ham)
        exp_spam = math.exp(log_spam - max_log)
        exp_ham  = math.exp(log_ham  - max_log)
        prob_spam = exp_spam / (exp_spam + exp_ham)
        return {
            'label':       1 if prob_spam > 0.5 else 0,
            'probability': round(prob_spam, 4),
            'is_spam':     prob_spam > 0.5,
        }


# ================================================================
# CACHE MODÈLE SPAM
# ================================================================
_spam_model_cache = None
_spam_model_lock  = threading.Lock()

def get_spam_model():
    global _spam_model_cache
    with _spam_model_lock:
        if _spam_model_cache is not None:
            return _spam_model_cache
        return _rebuild_spam_model()

def _rebuild_spam_model():
    global _spam_model_cache
    try:
        samples = SpamModelStore.query.all()
        if not samples:
            _seed_spam_data()
            samples = SpamModelStore.query.all()
        training = [(s.text, 1 if s.label == 'spam' else 0) for s in samples]
        _spam_model_cache = NLPEngine.train_naive_bayes(training)
        return _spam_model_cache
    except Exception as e:
        print(f"[spam] Erreur rebuild model : {e}")
        return {}

def _seed_spam_data():
    spam_examples = [
        "Gagnez de l'argent facilement maintenant cliquez ici",
        "Prix incroyable offre limitée achetez maintenant",
        "Vous avez gagné un voyage gratuit réclamez votre prix",
        "Urgent votre compte sera fermé vérifiez maintenant",
        "Agrandissez vos gains investissement garanti 500%",
        "Médicaments pas chers sans ordonnance livraison rapide",
        "Rencontrez des célibataires près de chez vous gratuit",
        "Gagnez 1000 euros par jour depuis chez vous",
        "Offre spéciale achetez maintenant avant la fin",
        "Cliquez pour gagner votre iPhone gratuit",
        "Nigerian prince fortune millions dollars besoin aide",
        "Free money click here now limited offer",
        "Win iPhone click here free prize winner",
        "Cheap medication no prescription fast delivery",
        "Make money fast work from home guaranteed",
    ]
    ham_examples = [
        "Ce produit est de très bonne qualité je recommande",
        "La livraison était rapide et l'emballage soigné",
        "Produit conforme à la description satisfait",
        "Bonne qualité prix raisonnable pour un tel article",
        "Service client réactif problème résolu rapidement",
        "Exactement ce que je cherchais très content",
        "Qualité premium matériaux solides durables",
        "Facile à utiliser manuel clair et précis",
        "Rapport qualité prix excellent je recommande vivement",
        "Livraison en temps voulu produit intact emballage parfait",
        "Great product works as described happy customer",
        "Fast shipping good quality recommended seller",
        "Excellent value for money highly recommend",
        "Product exactly as described very satisfied",
        "Good quality item arrived quickly well packaged",
    ]
    for txt in spam_examples:
        db.session.add(SpamModelStore(label='spam', text=txt))
    for txt in ham_examples:
        db.session.add(SpamModelStore(label='ham', text=txt))
    db.session.commit()

def invalidate_spam_cache():
    global _spam_model_cache
    with _spam_model_lock:
        _spam_model_cache = None


# ================================================================
# HELPERS PRODUITS
# ================================================================

def serialize_product(p):
    try:
        badges     = Badge.query.filter_by(product_id=p.id).all()
        badge_list = [b.nom for b in badges]
    except Exception:
        badge_list = []
    cat           = db.session.get(Category, p.category_id) if p.category_id else None
    stock_reserve = p.stock_reserve or 0
    import json as _json
    tags = []
    if p.tags_auto:
        try:
            tags = _json.loads(p.tags_auto)
        except Exception:
            tags = []
    return {
        'id':               p.id,
        'nom':              p.nom,
        'description':      p.description,
        'prix':             float(p.prix),
        'prix_original':    float(p.prix_original) if p.prix_original else None,
        'stock':            p.stock,
        'stock_dispo':      max(0, p.stock - stock_reserve),
        'image':            p.image,
        'shop_id':          p.shop_id,
        'category_id':      p.category_id,
        'category_nom':     cat.nom    if cat else None,
        'category_couleur': cat.couleur if cat else None,
        'sku':              p.sku,
        'disponible':       p.disponible,
        'promotion_active': p.promotion_active,
        'badges':           badge_list,
        'tags':             tags,
        'spam_score':       float(p.spam_score or 0),
    }

def _auto_tag_product(product):
    import json as _json
    text = f"{product.nom} {product.description or ''}"
    all_texts = [f"{p.nom} {p.description or ''}"
                 for p in Product.query.filter(Product.id != product.id).all()]
    all_texts.append(text)
    tags  = NLPEngine.extract_tags(text, all_texts, n=8)
    model = get_spam_model()
    spam  = NLPEngine.predict_spam(text, model)
    product.tags_auto  = _json.dumps(tags)
    product.spam_score = spam['probability']

def serialize_pickup(loc):
    return {
        'id':       loc.id,
        'nom':      loc.nom,
        'adresse':  loc.adresse,
        'horaires': loc.horaires,
        'actif':    loc.actif,
    }

def _serialize_order(o):
    user   = db.session.get(User, o.user_id)
    pickup = db.session.get(PickupLocation, o.pickup_location_id) if o.pickup_location_id else None
    items  = OrderItem.query.filter_by(order_id=o.id).all()
    items_data = []
    for it in items:
        p = db.session.get(Product, it.product_id)
        items_data.append({
            'product_id':  it.product_id,
            'product_nom': p.nom if p else '?',
            'quantity':    it.quantity,
            'prix':        float(it.prix_unitaire),
        })
    return {
        'id':              o.id,
        'total':           float(o.total),
        'status':          o.status,
        'payment_mode':    o.payment_mode,
        'payment_ref':     o.payment_ref,
        'user_id':         o.user_id,
        'user_nom':        user.nom if user else 'Inconnu',
        'items':           items_data,
        'date':            o.date_creation.strftime('%d/%m/%Y %H:%M') if o.date_creation else '',
        'date_pickup':     o.date_pickup.strftime('%d/%m/%Y %H:%M') if o.date_pickup else None,
        'note_pickup':     o.note_pickup,
        'pickup_location': serialize_pickup(pickup) if pickup else None,
    }

def require_admin(data):
    admin = db.session.get(User, data.get('admin_id'))
    if not admin or admin.role != 'admin':
        return None, (jsonify({'error': 'Accès refusé'}), 403)
    return admin, None

def require_marchand(data):
    user = db.session.get(User, data.get('user_id'))
    if not user or user.role != 'marchand':
        return None, (jsonify({'error': 'Accès refusé'}), 403)
    return user, None

# ================================================================
# HOME — health check Render
# ================================================================

@app.route('/')
def home():
    return "API MGShop OK"

@app.route('/health')
def health():
    return jsonify({'status': 'ok'}), 200

# ================================================================
# HELPERS MAIL + OTP
# ================================================================

def _generer_otp():
    return ''.join(random.choices(string.digits, k=6))

def _envoyer_mail_otp(destinataire, code, type_otp):
    try:
        if type_otp == 'register':
            sujet = 'MGShop - Code de verification'
            corps = (
                "Bonjour,\n\nVotre code de verification MGShop est :\n\n"
                f"    {code}\n\nCe code est valable 10 minutes.\n"
                "Si vous n'avez pas demande ce code, ignorez cet email.\n\n-- L'equipe MGShop"
            )
        else:
            sujet = 'MGShop - Reinitialisation de mot de passe'
            corps = (
                "Bonjour,\n\nVous avez demande a reinitialiser votre mot de passe MGShop.\n\n"
                f"Votre code de reinitialisation est :\n\n    {code}\n\n"
                "Ce code est valable 10 minutes.\n"
                "Si vous n'avez pas fait cette demande, ignorez cet email.\n\n-- L'equipe MGShop"
            )
        msg = Message(subject=sujet, recipients=[destinataire], body=corps)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"[mail] Erreur envoi : {e}")
        return False

def _nettoyer_otp_expires():
    import datetime
    with app.app_context():
        limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
        OTPCode.query.filter(OTPCode.created_at < limite).delete()
        db.session.commit()

def _lancer_nettoyage(delai_minutes=5):
    import time as _time
    def _run():
        _time.sleep(delai_minutes * 60)
        _nettoyer_otp_expires()
    t = threading.Thread(target=_run, daemon=True)
    t.start()

# ================================================================
# ROUTES OTP — INSCRIPTION
# ================================================================

@app.route('/users/send-otp', methods=['POST'])
def send_register_otp():
    data  = request.get_json()
    nom   = (data.get('nom') or '').strip()
    email = (data.get('email') or '').strip().lower()
    mdp   = (data.get('mot_de_passe') or '')
    if not nom or not email or not mdp:
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    if len(mdp) < 6:
        return jsonify({'error': 'Mot de passe trop court (6 caractères min)'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email deja utilise'}), 400
    code = _generer_otp()
    OTPCode.query.filter_by(email=email, type='register', used=False).update({'used': True})
    db.session.add(OTPCode(email=email, code=code, type='register'))
    db.session.commit()
    ok = _envoyer_mail_otp(email, code, 'register')
    if not ok:
        return jsonify({'error': "Impossible d'envoyer l'email."}), 500
    _lancer_nettoyage()
    return jsonify({'message': 'Code envoye', 'expires_in': 600})

@app.route('/users/verify-otp', methods=['POST'])
def verify_register_otp():
    import datetime
    data  = request.get_json()
    email = (data.get('email') or '').strip().lower()
    code  = (data.get('code')  or '').strip()
    nom   = (data.get('nom')   or '').strip()
    mdp   = (data.get('mot_de_passe') or '')
    if not all([email, code, nom, mdp]):
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
    otp = OTPCode.query.filter_by(email=email, code=code, type='register', used=False)\
                       .filter(OTPCode.created_at >= limite)\
                       .order_by(OTPCode.id.desc()).first()
    if not otp:
        return jsonify({'error': 'Code invalide ou expire'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email deja utilise'}), 400
    otp.used = True
    user = User(nom=nom, email=email, mot_de_passe=generate_password_hash(mdp), role='user')
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Compte cree', 'id': user.id,
                    'nom': user.nom, 'email': user.email, 'role': user.role})

# ================================================================
# ROUTES OTP — RESET MOT DE PASSE
# ================================================================

@app.route('/password/send-otp', methods=['POST'])
def send_reset_otp():
    data  = request.get_json()
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'Email requis'}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'message': 'Si cet email existe, un code a ete envoye', 'expires_in': 600})
    code = _generer_otp()
    OTPCode.query.filter_by(email=email, type='reset', used=False).update({'used': True})
    db.session.add(OTPCode(email=email, code=code, type='reset'))
    db.session.commit()
    ok = _envoyer_mail_otp(email, code, 'reset')
    if not ok:
        return jsonify({'error': "Impossible d'envoyer l'email."}), 500
    _lancer_nettoyage()
    return jsonify({'message': 'Si cet email existe, un code a ete envoye', 'expires_in': 600})

@app.route('/password/verify-otp', methods=['POST'])
def verify_reset_otp():
    import datetime, secrets as _secrets
    data  = request.get_json()
    email = (data.get('email') or '').strip().lower()
    code  = (data.get('code')  or '').strip()
    limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
    otp = OTPCode.query.filter_by(email=email, code=code, type='reset', used=False)\
                       .filter(OTPCode.created_at >= limite)\
                       .order_by(OTPCode.id.desc()).first()
    if not otp:
        return jsonify({'error': 'Code invalide ou expire'}), 400
    otp.used = True
    token = _secrets.token_urlsafe(32)
    db.session.add(OTPCode(email=email, code=token, type='reset_verified'))
    db.session.commit()
    return jsonify({'message': 'Code verifie', 'token': token})

@app.route('/password/reset', methods=['POST'])
def reset_password():
    import datetime
    data    = request.get_json()
    email   = (data.get('email')   or '').strip().lower()
    token   = (data.get('token')   or '').strip()
    nouveau = (data.get('nouveau_mdp') or data.get('nouveau_mot_de_passe') or '')
    if not all([email, token, nouveau]):
        return jsonify({'error': 'Tous les champs sont requis'}), 400
    if len(nouveau) < 6:
        return jsonify({'error': 'Mot de passe trop court (6 caracteres min)'}), 400
    limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
    otp = OTPCode.query.filter_by(email=email, code=token, type='reset_verified', used=False)\
                       .filter(OTPCode.created_at >= limite)\
                       .order_by(OTPCode.id.desc()).first()
    if not otp:
        return jsonify({'error': 'Token invalide ou expire'}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    otp.used = True
    user.mot_de_passe = generate_password_hash(nouveau)
    db.session.commit()
    return jsonify({'message': 'Mot de passe modifie avec succes'})

# ================================================================
# USERS
# ================================================================

@app.route('/users', methods=['GET'])
def get_users():
    return jsonify([{'id': u.id, 'nom': u.nom, 'email': u.email, 'role': u.role}
                    for u in User.query.all()])

@app.route('/users', methods=['POST'])
def add_user():
    data  = request.get_json()
    email = (data.get('email') or '').strip().lower()
    code  = (data.get('code')  or '').strip()
    if code:
        import datetime
        nom = (data.get('nom') or '').strip()
        mdp = (data.get('mot_de_passe') or '')
        if not nom or not mdp:
            return jsonify({'error': 'Nom et mot de passe requis'}), 400
        limite = datetime.datetime.utcnow() - datetime.timedelta(minutes=10)
        otp = OTPCode.query.filter_by(email=email, type='register', used=False)\
                           .filter(OTPCode.created_at >= limite)\
                           .order_by(OTPCode.id.desc()).first()
        if not otp:
            return jsonify({'error': 'Code invalide ou expiré. Recommencez.'}), 400
        if otp.code != code:
            return jsonify({'error': 'Code incorrect'}), 400
        if User.query.filter_by(email=email).first():
            otp.used = True; db.session.commit()
            return jsonify({'error': 'Email déjà utilisé'}), 400
        otp.used = True
        user = User(nom=nom, email=email, mot_de_passe=generate_password_hash(mdp), role='user')
        db.session.add(user)
        db.session.commit()
        return jsonify({'message': 'Compte créé avec succès', 'id': user.id})
    nom = (data.get('nom') or '').strip()
    mdp = data.get('mot_de_passe') or ''
    if not nom or not email or not mdp:
        return jsonify({'error': 'Champs obligatoires manquants'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email déjà utilisé'}), 400
    user = User(nom=nom, email=email, mot_de_passe=generate_password_hash(mdp), role='user')
    db.session.add(user)
    db.session.commit()
    return jsonify({'message': 'Utilisateur créé', 'id': user.id})

@app.route('/login', methods=['POST'])
def login():
    data  = request.get_json()
    email = (data.get('email') or '').strip().lower()
    mdp   = data.get('mot_de_passe') or ''
    user  = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.mot_de_passe, mdp):
        return jsonify({'error': 'Email ou mot de passe incorrect'}), 401
    return jsonify({'id': user.id, 'nom': user.nom, 'email': user.email, 'role': user.role})

@app.route('/users/role', methods=['POST'])
def change_user_role():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    user     = db.session.get(User, data.get('user_id'))
    new_role = data.get('role')
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if user.role == 'admin':
        return jsonify({'error': 'Impossible de modifier un admin'}), 403
    if new_role not in ('user', 'marchand'):
        return jsonify({'error': 'Rôle invalide'}), 400
    user.role = new_role
    db.session.commit()
    return jsonify({'message': 'Rôle modifié'})

@app.route('/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    if user.role == 'admin':
        return jsonify({'error': 'Impossible de supprimer un admin'}), 403
    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'Utilisateur supprimé'})

# ================================================================
# NETTOYAGE USERS TEMPORAIRES
# ================================================================

@app.route('/users/cleanup-tmp', methods=['POST'])
def cleanup_tmp_users():
    """Supprime les visiteurs temporaires (@mgshop.tmp) sans commande active."""
    data     = request.get_json() or {}
    admin_id = data.get('admin_id')
    admin, err = require_admin({'admin_id': admin_id})
    if err: return err
    tmp_users = User.query.filter(User.email.like('%@mgshop.tmp')).all()
    deleted = 0
    kept    = 0
    for u in tmp_users:
        has_active = Order.query.filter(
            Order.user_id == u.id,
            Order.status.in_(['pending', 'awaiting_confirmation', 'ready_for_pickup'])
        ).first()
        if has_active:
            kept += 1
            continue
        UserProductInteraction.query.filter_by(user_id=u.id).delete()
        UserCategoryInteraction.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        deleted += 1
    db.session.commit()
    return jsonify({'message': f'{deleted} compte(s) temporaire(s) supprimé(s), {kept} conservé(s)'})

# ================================================================
# SHOPS
# ================================================================

@app.route('/shops', methods=['GET'])
def get_shops():
    return jsonify([{'id': s.id, 'nom': s.nom, 'description': s.description,
                     'logo': s.logo, 'owner_id': s.owner_id}
                    for s in Shop.query.filter_by(valide=True).all()])

@app.route('/shops/pending', methods=['GET'])
def pending_shops():
    return jsonify([{'id': s.id, 'nom': s.nom, 'description': s.description,
                     'owner_id': s.owner_id}
                    for s in Shop.query.filter_by(valide=False).all()])

@app.route('/shops', methods=['POST'])
def create_shop():
    data      = request.get_json()
    user, err = require_marchand(data)
    if err: return err
    if Shop.query.filter_by(owner_id=user.id).first():
        return jsonify({'error': 'Vous avez déjà une boutique'}), 400
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'error': 'Le nom est obligatoire'}), 400
    shop = Shop(nom=nom, description=(data.get('description') or '').strip(),
                logo=data.get('logo'), owner_id=user.id)
    db.session.add(shop)
    db.session.commit()
    return jsonify({'message': 'Boutique créée, en attente de validation'})

@app.route('/shops/<int:shop_id>', methods=['GET'])
def get_shop(shop_id):
    shop = db.session.get(Shop, shop_id)
    if not shop:
        return jsonify({'error': 'Boutique introuvable'}), 404
    owner = db.session.get(User, shop.owner_id)
    nb_produits = Product.query.filter_by(shop_id=shop.id, disponible=True).count()
    return jsonify({
        'id': shop.id, 'nom': shop.nom, 'description': shop.description,
        'logo': shop.logo, 'owner_nom': owner.nom if owner else '?',
        'nb_produits': nb_produits, 'valide': shop.valide,
    })

@app.route('/shops/validate', methods=['POST'])
def validate_shop():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    shop = db.session.get(Shop, data.get('shop_id'))
    if not shop:
        return jsonify({'error': 'Boutique introuvable'}), 404
    shop.valide = True
    db.session.commit()
    return jsonify({'message': 'Boutique validée'})

# ================================================================
# PICKUP LOCATIONS
# ================================================================

@app.route('/pickup-locations', methods=['GET'])
def get_pickup_locations():
    locs = PickupLocation.query.filter_by(actif=True).order_by(PickupLocation.nom).all()
    return jsonify([serialize_pickup(l) for l in locs])

@app.route('/pickup-locations/all', methods=['GET'])
def get_all_pickup_locations():
    locs = PickupLocation.query.order_by(PickupLocation.nom).all()
    return jsonify([serialize_pickup(l) for l in locs])

@app.route('/pickup-locations', methods=['POST'])
def add_pickup_location():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    nom     = (data.get('nom') or '').strip()
    adresse = (data.get('adresse') or '').strip()
    if not nom or not adresse:
        return jsonify({'error': 'Nom et adresse obligatoires'}), 400
    loc = PickupLocation(nom=nom, adresse=adresse,
                         horaires=(data.get('horaires') or '').strip(), actif=True)
    db.session.add(loc)
    db.session.commit()
    return jsonify({'message': 'Lieu créé', 'location': serialize_pickup(loc)})

@app.route('/pickup-locations/<int:loc_id>', methods=['PUT'])
def update_pickup_location(loc_id):
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    loc = db.session.get(PickupLocation, loc_id)
    if not loc:
        return jsonify({'error': 'Lieu introuvable'}), 404
    if 'nom'      in data: loc.nom      = data['nom'].strip()
    if 'adresse'  in data: loc.adresse  = data['adresse'].strip()
    if 'horaires' in data: loc.horaires = data['horaires'].strip()
    if 'actif'    in data: loc.actif    = bool(data['actif'])
    db.session.commit()
    return jsonify({'message': 'Lieu mis à jour', 'location': serialize_pickup(loc)})

@app.route('/pickup-locations/<int:loc_id>', methods=['DELETE'])
def delete_pickup_location(loc_id):
    data       = request.get_json() or {}
    admin_id   = request.args.get('admin_id', type=int) or data.get('admin_id')
    admin, err = require_admin({'admin_id': admin_id})
    if err: return err
    loc = db.session.get(PickupLocation, loc_id)
    if not loc:
        return jsonify({'error': 'Lieu introuvable'}), 404
    Order.query.filter_by(pickup_location_id=loc_id).update({'pickup_location_id': None})
    db.session.delete(loc)
    db.session.commit()
    return jsonify({'message': 'Lieu supprimé'})

@app.route('/pickup-locations/stats', methods=['GET'])
def pickup_stats():
    locs  = PickupLocation.query.all()
    stats = []
    for l in locs:
        base  = Order.query.filter_by(pickup_location_id=l.id)
        stats.append({
            'id': l.id, 'nom': l.nom, 'actif': l.actif,
            'total':      base.count(),
            'ready':      base.filter_by(status='ready_for_pickup').count(),
            'picked_up':  base.filter_by(status='picked_up').count(),
            'not_picked': base.filter_by(status='not_picked_up').count(),
        })
    return jsonify(stats)

# ================================================================
# CATEGORIES
# ================================================================

@app.route('/categories', methods=['GET'])
def get_categories():
    cats   = Category.query.order_by(Category.nom).all()
    result = []
    for c in cats:
        nb = db.session.query(func.count(Product.id))\
               .filter(Product.category_id == c.id,
                       Product.disponible  == True).scalar() or 0
        result.append({'id': c.id, 'nom': c.nom, 'description': c.description,
                        'couleur': c.couleur, 'nb_produits': nb})
    return jsonify(result)

@app.route('/categories', methods=['POST'])
def add_category():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    nom = (data.get('nom') or '').strip()
    if not nom:
        return jsonify({'error': 'Nom obligatoire'}), 400
    if Category.query.filter_by(nom=nom).first():
        return jsonify({'error': 'Catégorie déjà existante'}), 400
    cat = Category(nom=nom, description=(data.get('description') or '').strip(),
                   couleur=data.get('couleur', '#6366f1'))
    db.session.add(cat)
    db.session.commit()
    return jsonify({'message': 'Catégorie créée', 'id': cat.id, 'nom': cat.nom,
                    'couleur': cat.couleur, 'description': cat.description, 'nb_produits': 0})

@app.route('/categories/<int:cat_id>', methods=['PUT'])
def update_category(cat_id):
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    cat = db.session.get(Category, cat_id)
    if not cat:
        return jsonify({'error': 'Introuvable'}), 404
    if 'nom'         in data: cat.nom         = data['nom'].strip()
    if 'description' in data: cat.description = data['description'].strip()
    if 'couleur'     in data: cat.couleur     = data['couleur']
    db.session.commit()
    return jsonify({'message': 'Catégorie mise à jour'})

@app.route('/categories/<int:cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    data       = request.get_json() or {}
    admin_id   = request.args.get('admin_id', type=int) or data.get('admin_id')
    admin, err = require_admin({'admin_id': admin_id})
    if err: return err
    cat = db.session.get(Category, cat_id)
    if not cat:
        return jsonify({'error': 'Introuvable'}), 404
    Product.query.filter_by(category_id=cat_id).update({'category_id': None})
    db.session.delete(cat)
    db.session.commit()
    return jsonify({'message': 'Catégorie supprimée'})

@app.route('/categories/stats', methods=['GET'])
def categories_stats():
    cats  = Category.query.order_by(Category.nom).all()
    stats = []
    for c in cats:
        produits    = Product.query.filter_by(category_id=c.id).all()
        stock_total = sum(p.stock for p in produits)
        rev = db.session.query(
                func.sum(OrderItem.prix_unitaire * OrderItem.quantity))\
            .join(Product, OrderItem.product_id == Product.id)\
            .join(Order,   OrderItem.order_id   == Order.id)\
            .filter(Product.category_id == c.id,
                    Order.status.in_(['paid', 'ready_for_pickup', 'picked_up'])).scalar() or 0
        stats.append({'id': c.id, 'nom': c.nom, 'couleur': c.couleur,
                       'nb_produits': len(produits),
                       'stock_total': stock_total,
                       'revenus':     float(rev)})
    return jsonify(stats)

# ================================================================
# IA RECOMMANDATION — MODELS
# ================================================================

class UserProductInteraction(db.Model):
    __tablename__ = 'user_product_interactions'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    nb_vues    = db.Column(db.Integer, default=0)
    nb_panier  = db.Column(db.Integer, default=0)
    nb_achat   = db.Column(db.Integer, default=0)
    nb_ignore  = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'product_id', name='uq_user_product'),)

class UserCategoryInteraction(db.Model):
    __tablename__ = 'user_category_interactions'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    nb_clics    = db.Column(db.Integer, default=0)
    __table_args__ = (db.UniqueConstraint('user_id', 'category_id', name='uq_user_category'),)

# ================================================================
# IA RECOMMANDATION — ENGINE
# ================================================================

class IARecommendation:
    def __init__(self, user_id: int):
        self.user_id = user_id

    def _get_or_create(self, product_id: int) -> UserProductInteraction:
        inter = UserProductInteraction.query.filter_by(
            user_id=self.user_id, product_id=product_id
        ).first()
        if not inter:
            inter = UserProductInteraction(user_id=self.user_id, product_id=product_id)
            db.session.add(inter)
            db.session.flush()
        return inter

    def apprendre(self, product_id: int, action: str):
        inter = self._get_or_create(product_id)
        if action == 'vue':
            inter.nb_vues   += 1
        elif action == 'panier':
            inter.nb_vues   += 1
            inter.nb_panier += 1
        elif action == 'achat':
            inter.nb_achat  += 1
        elif action == 'ignore':
            inter.nb_vues   += 1
            inter.nb_ignore += 1
        db.session.commit()

    def apprendre_bulk(self, interactions: list):
        for item in interactions:
            pid    = item.get('product_id')
            action = item.get('action')
            if not pid or action not in ('vue', 'panier', 'achat', 'ignore'):
                continue
            inter = self._get_or_create(pid)
            if action == 'vue':
                inter.nb_vues   += 1
            elif action == 'panier':
                inter.nb_vues   += 1
                inter.nb_panier += 1
            elif action == 'achat':
                inter.nb_achat  += 1
            elif action == 'ignore':
                inter.nb_vues   += 1
                inter.nb_ignore += 1
        db.session.commit()

    def _taux_panier(self, inter) -> float:
        if not inter or inter.nb_vues == 0:
            return 0.0
        return inter.nb_panier / inter.nb_vues

    def _taux_achat(self, inter) -> float:
        if not inter or inter.nb_vues == 0:
            return 0.0
        return inter.nb_achat / inter.nb_vues

    def _prix_prefere(self):
        inters = UserProductInteraction.query.filter(
            UserProductInteraction.user_id == self.user_id,
            db.or_(UserProductInteraction.nb_panier > 0, UserProductInteraction.nb_achat > 0)
        ).all()
        if not inters:
            return None
        prix_list = []
        for i in inters:
            p = db.session.get(Product, i.product_id)
            if p:
                poids = i.nb_achat * 2 + i.nb_panier
                prix_list.extend([float(p.prix)] * poids)
        if not prix_list:
            return None
        prix_list.sort()
        return prix_list[len(prix_list) // 2]

    def _categories_preferees(self) -> dict:
        scores = {}
        for ci in UserCategoryInteraction.query.filter_by(user_id=self.user_id).all():
            scores[ci.category_id] = scores.get(ci.category_id, 0.0) + min(ci.nb_clics, 10) * 1.0
        for i in UserProductInteraction.query.filter_by(user_id=self.user_id).all():
            prod = db.session.get(Product, i.product_id)
            if not prod or not prod.category_id:
                continue
            affinite = i.nb_achat * 3 + i.nb_panier * 2 + i.nb_vues * 0.5 - i.nb_ignore * 0.5
            scores[prod.category_id] = scores.get(prod.category_id, 0.0) + affinite
        return scores

    def _score_nlp(self, product: Product, user_tags: list) -> float:
        if not user_tags or not product.tags_auto:
            return 0.0
        import json as _json
        try:
            prod_tags = _json.loads(product.tags_auto)
        except Exception:
            return 0.0
        if not prod_tags:
            return 0.0
        common = set(user_tags) & set(prod_tags)
        return len(common) / max(len(user_tags), len(prod_tags), 1) * 15.0

    def _get_user_preferred_tags(self) -> list:
        import json as _json
        inters = UserProductInteraction.query.filter(
            UserProductInteraction.user_id == self.user_id,
            db.or_(
                UserProductInteraction.nb_panier > 0,
                UserProductInteraction.nb_achat  > 0,
                UserProductInteraction.nb_vues   > 0,
            )
        ).all()
        all_tags = []
        for i in inters:
            p = db.session.get(Product, i.product_id)
            if p and p.tags_auto:
                try:
                    tags   = _json.loads(p.tags_auto)
                    weight = i.nb_achat * 3 + i.nb_panier * 2 + i.nb_vues
                    all_tags.extend(tags * max(weight, 1))
                except Exception:
                    pass
        return all_tags

    def _score(self, product: Product, inter, prix_pref, cat_scores) -> float:
        s_panier = self._taux_panier(inter) * 40.0
        s_achat  = self._taux_achat(inter)  * 60.0
        max_cat  = max(cat_scores.values()) if cat_scores else 1.0
        s_cat    = (cat_scores.get(product.category_id, 0.0) / max(max_cat, 1)) * 20.0
        if prix_pref and product.prix:
            dist_prix = abs(float(product.prix) - prix_pref)
            s_prix = max(0.0, 20.0 - dist_prix / 1000.0 * 20.0)
        else:
            s_prix = 0.0
        nb_vues    = inter.nb_vues if inter else 0
        s_penalite = min(nb_vues * 0.3, 10.0)
        s_nouveau  = 5.0 if nb_vues == 0 else 0.0
        return s_panier + s_achat + s_cat + s_prix + s_nouveau - s_penalite

    def recommander(self, n: int = 8, exclure_ids: list = None) -> list:
        import random as _random
        exclure  = set(exclure_ids or [])
        produits = Product.query.filter(Product.disponible == True).all()
        produits = [p for p in produits if p.id not in exclure]
        if not produits:
            return []
        en_stock = [p for p in produits if (p.stock - (p.stock_reserve or 0)) > 0]
        epuises  = [p for p in produits if (p.stock - (p.stock_reserve or 0)) <= 0]
        cat_scores = self._categories_preferees()
        prix_pref  = self._prix_prefere()
        has_prefs  = bool(cat_scores or prix_pref)
        if not has_prefs:
            cats = Category.query.all()
            result_ids = []
            used_ids   = set()
            cat_list = list(cats)
            _random.shuffle(cat_list)
            for cat in cat_list:
                candidates = [p for p in en_stock if p.category_id == cat.id and p.id not in used_ids]
                if not candidates:
                    candidates = [p for p in epuises if p.category_id == cat.id and p.id not in used_ids]
                if candidates:
                    chosen = _random.choice(candidates)
                    result_ids.append(chosen.id)
                    used_ids.add(chosen.id)
            remaining = [p for p in en_stock if p.id not in used_ids]
            _random.shuffle(remaining)
            for p in remaining:
                if len(result_ids) >= n:
                    break
                result_ids.append(p.id)
                used_ids.add(p.id)
            return result_ids[:n]
        inters_map = {i.product_id: i for i in
                      UserProductInteraction.query.filter_by(user_id=self.user_id).all()}
        user_tags  = self._get_user_preferred_tags()
        def score_avec_stock(p):
            stock_dispo = p.stock - (p.stock_reserve or 0)
            bonus_stock = 15.0 if stock_dispo > 0 else -50.0
            base_score  = self._score(p, inters_map.get(p.id), prix_pref, cat_scores)
            nlp_bonus   = self._score_nlp(p, user_tags)
            return base_score + bonus_stock + nlp_bonus
        scored_stock  = sorted(en_stock, key=score_avec_stock, reverse=True)
        scored_epuise = sorted(epuises,  key=score_avec_stock, reverse=True)
        scored_all    = scored_stock + scored_epuise
        result  = []
        ids_set = set()
        for p in scored_all:
            if len(result) >= n:
                break
            if _random.random() < 0.85:
                result.append(p.id)
                ids_set.add(p.id)
        for p in scored_all:
            if len(result) >= n:
                break
            if p.id not in ids_set:
                result.append(p.id)
                ids_set.add(p.id)
        return result[:n]

    def recommander_similaires(self, product_id: int, n: int = 6) -> list:
        target = db.session.get(Product, product_id)
        if not target:
            return []
        all_prods = Product.query.filter(
            Product.disponible == True,
            Product.id != product_id
        ).all()
        if not all_prods:
            return []
        target_text = f"{target.nom} {target.description or ''}"
        all_texts   = [f"{p.nom} {p.description or ''}" for p in all_prods]
        corpus      = [target_text] + all_texts
        corpus_tok  = [NLPEngine.preprocess(t) for t in corpus]
        idf         = NLPEngine.compute_idf(corpus_tok)
        vocab       = list(idf.keys())
        target_tfidf = NLPEngine.compute_tfidf(corpus_tok[0], idf)
        target_vec   = NLPEngine.vectorize(target_tfidf, vocab)
        scored = []
        for i, p in enumerate(all_prods):
            p_tfidf = NLPEngine.compute_tfidf(corpus_tok[i + 1], idf)
            p_vec   = NLPEngine.vectorize(p_tfidf, vocab)
            sim     = NLPEngine.cosine_similarity(target_vec, p_vec)
            if sim > 0.05:
                scored.append((p, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            {**serialize_product(p), 'similarity': round(sim, 3)}
            for p, sim in scored[:n]
        ]

    def stats(self) -> dict:
        inters = UserProductInteraction.query.filter_by(user_id=self.user_id).all()
        result = []
        for i in inters:
            p = db.session.get(Product, i.product_id)
            if not p: continue
            result.append({
                'product_id':  p.id, 'product_nom': p.nom,
                'prix':        float(p.prix), 'category_id': p.category_id,
                'nb_vues':     i.nb_vues, 'nb_panier':  i.nb_panier,
                'nb_achat':    i.nb_achat, 'nb_ignore':  i.nb_ignore,
                'taux_panier': round(self._taux_panier(i), 2),
                'taux_achat':  round(self._taux_achat(i), 2),
            })
        return {
            'user_id':      self.user_id,
            'prix_prefere': self._prix_prefere(),
            'categories':   self._categories_preferees(),
            'interactions': result,
        }

# ================================================================
# PRODUCTS
# ================================================================

@app.route('/products', methods=['GET'])
def get_products():
    import random as _random
    shop_id     = request.args.get('shop_id',     type=int)
    category_id = request.args.get('category_id', type=int)
    owner_mode  = request.args.get('owner',        type=int)
    user_id     = request.args.get('user_id',      type=int)
    query = Product.query
    if shop_id:     query = query.filter_by(shop_id=shop_id)
    if category_id: query = query.filter_by(category_id=category_id)
    if not owner_mode:
        query = query.filter(Product.disponible == True)
    produits = query.all()
    if user_id:
        cat_scores = IARecommendation(user_id)._categories_preferees()
        has_prefs  = bool(cat_scores)
        if has_prefs:
            ia         = IARecommendation(user_id)
            prix_pref  = ia._prix_prefere()
            inters_map = {i.product_id: i for i in
                          UserProductInteraction.query.filter_by(user_id=user_id).all()}
            def sort_key(p):
                stock_dispo = p.stock - (p.stock_reserve or 0)
                bonus_stock = 15.0 if stock_dispo > 0 else -30.0
                score_ia    = ia._score(p, inters_map.get(p.id), prix_pref, cat_scores)
                return score_ia + bonus_stock
            produits = sorted(produits, key=sort_key, reverse=True)
        else:
            en_stock = [p for p in produits if (p.stock - (p.stock_reserve or 0)) > 0]
            epuises  = [p for p in produits if (p.stock - (p.stock_reserve or 0)) <= 0]
            _random.shuffle(en_stock)
            _random.shuffle(epuises)
            produits = en_stock + epuises
    else:
        produits = sorted(produits,
                          key=lambda p: (-(p.stock - (p.stock_reserve or 0)), p.id))
    return jsonify([serialize_product(p) for p in produits])

@app.route('/products', methods=['POST'])
def add_product():
    data      = request.get_json()
    user, err = require_marchand(data)
    if err: return err
    shop = db.session.get(Shop, data.get('shop_id'))
    if not shop or shop.owner_id != user.id:
        return jsonify({'error': 'Boutique introuvable'}), 404
    if not shop.valide:
        return jsonify({'error': "Boutique non validée"}), 403
    nom  = (data.get('nom') or '').strip()
    prix = data.get('prix')
    if not nom:
        return jsonify({'error': 'Nom obligatoire'}), 400
    if prix is None or float(prix) < 0:
        return jsonify({'error': 'Prix invalide'}), 400
    stock = data.get('stock', 0)
    if int(stock) < 0:
        return jsonify({'error': 'Stock invalide'}), 400
    sku = data.get('sku') or f"{data.get('shop_id')}-{int(time.time())}"
    product = Product(
        nom=nom, description=(data.get('description') or '').strip(),
        prix=float(prix), prix_original=float(data.get('prix_original') or prix),
        promotion_active=bool(data.get('promotion_active', False)),
        stock=int(stock), stock_reserve=0,
        image=data.get('image'), category_id=data.get('category_id'),
        shop_id=shop.id, sku=sku,
    )
    db.session.add(product)
    db.session.flush()
    try:
        _auto_tag_product(product)
    except Exception as e:
        print(f"[nlp] tag auto error: {e}")
    db.session.commit()
    return jsonify({'message': 'Produit ajouté', 'product': serialize_product(product)})

# ================================================================
# ROUTES PRODUITS — SUGGESTIONS & INTERACTIONS
# ================================================================

@app.route('/products/suggestions', methods=['GET'])
def get_suggestions():
    user_id = request.args.get('user_id', type=int)
    n       = request.args.get('n', 8, type=int)
    if not user_id:
        return jsonify({'error': 'user_id manquant'}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    ia          = IARecommendation(user_id)
    produit_ids = ia.recommander(n=n)
    produits    = [serialize_product(db.session.get(Product, pid))
                   for pid in produit_ids
                   if db.session.get(Product, pid)]
    cat_scores  = ia._categories_preferees()
    has_prefs   = bool(cat_scores)
    return jsonify({
        'suggestions':  produits,
        'prix_prefere': ia._prix_prefere(),
        'nb_total':     len(produits),
        'has_prefs':    has_prefs,
        'top_categories': sorted(cat_scores.items(), key=lambda x: x[1], reverse=True)[:3],
    })

@app.route('/products/<int:product_id>/similaires', methods=['GET'])
def get_similaires(product_id):
    n       = request.args.get('n', 6, type=int)
    user_id = request.args.get('user_id', type=int)
    ia      = IARecommendation(user_id or 0)
    result  = ia.recommander_similaires(product_id, n=n)
    return jsonify({'similaires': result, 'nb': len(result)})

@app.route('/categories/interact', methods=['POST'])
def category_interact():
    data        = request.get_json()
    user_id     = data.get('user_id')
    category_id = data.get('category_id')
    if not user_id or not category_id:
        return jsonify({'error': 'user_id et category_id requis'}), 400
    inter = UserCategoryInteraction.query.filter_by(
        user_id=user_id, category_id=category_id).first()
    if not inter:
        inter = UserCategoryInteraction(user_id=user_id, category_id=category_id, nb_clics=0)
        db.session.add(inter)
    inter.nb_clics += 1
    db.session.commit()
    return jsonify({'message': 'Clic enregistré', 'nb_clics': inter.nb_clics})

@app.route('/products/interact', methods=['POST'])
def product_interact():
    data       = request.get_json()
    user_id    = data.get('user_id')
    product_id = data.get('product_id')
    action     = data.get('action')
    if not user_id or not product_id or action not in ('vue', 'panier', 'achat', 'ignore'):
        return jsonify({'error': 'Paramètres invalides'}), 400
    user    = db.session.get(User, user_id)
    product = db.session.get(Product, product_id)
    if not user or not product:
        return jsonify({'error': 'Utilisateur ou produit introuvable'}), 404
    ia = IARecommendation(user_id)
    ia.apprendre(product_id, action)
    if product.category_id and action in ('vue', 'panier', 'achat'):
        ci = UserCategoryInteraction.query.filter_by(
            user_id=user_id, category_id=product.category_id).first()
        if not ci:
            ci = UserCategoryInteraction(
                user_id=user_id, category_id=product.category_id, nb_clics=0)
            db.session.add(ci)
        weight = {'vue': 1, 'panier': 2, 'achat': 3}.get(action, 0)
        ci.nb_clics += weight
        db.session.commit()
    return jsonify({'message': 'Interaction enregistrée'})

@app.route('/products/interact/bulk', methods=['POST'])
def product_interact_bulk():
    data         = request.get_json()
    user_id      = data.get('user_id')
    interactions = data.get('interactions', [])
    n            = data.get('n', 8)
    if not user_id:
        return jsonify({'error': 'user_id manquant'}), 400
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Utilisateur introuvable'}), 404
    ia = IARecommendation(user_id)
    ia.apprendre_bulk(interactions)
    for item in interactions:
        pid    = item.get('product_id')
        action = item.get('action')
        if pid and action in ('vue', 'panier', 'achat'):
            product = db.session.get(Product, pid)
            if product and product.category_id:
                ci = UserCategoryInteraction.query.filter_by(
                    user_id=user_id, category_id=product.category_id).first()
                if not ci:
                    ci = UserCategoryInteraction(
                        user_id=user_id, category_id=product.category_id, nb_clics=0)
                    db.session.add(ci)
                weight = {'vue': 1, 'panier': 2, 'achat': 3}.get(action, 0)
                ci.nb_clics += weight
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    produit_ids = ia.recommander(n=n)
    produits    = [serialize_product(db.session.get(Product, pid))
                   for pid in produit_ids
                   if db.session.get(Product, pid)]
    cat_scores  = ia._categories_preferees()
    return jsonify({
        'message':    'Interactions enregistrées',
        'suggestions': produits,
        'has_prefs':  bool(cat_scores),
        'nb_total':   len(produits),
    })

@app.route('/products/ia-stats', methods=['GET'])
def ia_stats():
    user_id = request.args.get('user_id', type=int)
    if not user_id:
        return jsonify({'error': 'user_id manquant'}), 400
    ia = IARecommendation(user_id)
    return jsonify(ia.stats())

@app.route('/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    data      = request.get_json()
    user, err = require_marchand(data)
    if err: return err
    product = db.session.get(Product, product_id)
    if not product:
        return jsonify({'error': 'Introuvable'}), 404
    shop = db.session.get(Shop, product.shop_id)
    if not shop or shop.owner_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    changed_text = False
    if 'nom'             in data: product.nom              = data['nom'].strip();  changed_text = True
    if 'description'     in data: product.description      = data['description'].strip(); changed_text = True
    if 'prix'            in data: product.prix             = float(data['prix'])
    if 'stock'           in data: product.stock            = int(data['stock'])
    if 'image'           in data: product.image            = data['image']
    if 'disponible'      in data: product.disponible       = bool(data['disponible'])
    if 'promotion_active'in data: product.promotion_active = bool(data['promotion_active'])
    if 'prix_original'   in data: product.prix_original    = float(data['prix_original'])
    if 'category_id'     in data: product.category_id      = data['category_id']
    if changed_text:
        try:
            _auto_tag_product(product)
        except Exception as e:
            print(f"[nlp] tag auto update error: {e}")
    db.session.commit()
    return jsonify({'message': 'Produit mis à jour', 'product': serialize_product(product)})

@app.route('/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    user_id = (request.args.get('user_id', type=int)
               or (request.get_json(silent=True) or {}).get('user_id'))
    user, err = require_marchand({'user_id': user_id})
    if err: return err
    product = db.session.get(Product, product_id)
    if not product:
        return jsonify({'error': 'Introuvable'}), 404
    shop = db.session.get(Shop, product.shop_id)
    if not shop or shop.owner_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    db.session.delete(product)
    db.session.commit()
    return jsonify({'message': 'Produit supprimé'})

@app.route('/products/badge', methods=['POST'])
def add_badge():
    data      = request.get_json()
    user, err = require_marchand(data)
    if err: return err
    product = db.session.get(Product, data.get('product_id'))
    if not product:
        return jsonify({'error': 'Introuvable'}), 404
    shop = db.session.get(Shop, product.shop_id)
    if not shop or shop.owner_id != user.id:
        return jsonify({'error': 'Accès refusé'}), 403
    nom_badge = (data.get('badge') or '').strip()
    if not nom_badge:
        return jsonify({'error': 'Nom badge obligatoire'}), 400
    db.session.add(Badge(product_id=product.id, nom=nom_badge))
    db.session.commit()
    return jsonify({'message': 'Badge ajouté'})

# ================================================================
# ROUTES NLP
# ================================================================

@app.route('/nlp/tags', methods=['POST'])
def nlp_extract_tags():
    data  = request.get_json()
    text  = data.get('text', '')
    texts = data.get('texts', [])
    n     = int(data.get('n', 8))
    tags  = NLPEngine.extract_tags(text, texts if texts else None, n=n)
    return jsonify({'tags': tags, 'count': len(tags)})

@app.route('/nlp/stats', methods=['POST'])
def nlp_text_stats():
    data  = request.get_json()
    text  = data.get('text', '')
    texts = data.get('texts', [])
    stats = NLPEngine.text_stats(text, texts or None)
    return jsonify(stats)

@app.route('/nlp/similarity', methods=['POST'])
def nlp_similarity():
    data  = request.get_json()
    texts = data.get('texts', [])
    if len(texts) < 2:
        return jsonify({'error': 'Au moins 2 textes requis'}), 400
    mat   = NLPEngine.similarity_matrix(texts)
    pairs = []
    n     = len(texts)
    for i in range(n):
        for j in range(i + 1, n):
            pairs.append({'i': i, 'j': j, 'score': round(mat[i][j], 4)})
    pairs.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({'matrix': mat, 'top_pairs': pairs[:10], 'most_similar': pairs[0] if pairs else None})

@app.route('/nlp/spam/predict', methods=['POST'])
def nlp_spam_predict():
    data = request.get_json()
    text = data.get('text', '')
    if not text.strip():
        return jsonify({'error': 'Texte requis'}), 400
    return jsonify(NLPEngine.predict_spam(text, get_spam_model()))

@app.route('/nlp/spam/train', methods=['POST'])
def nlp_spam_train():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    text  = (data.get('text') or '').strip()
    label = data.get('label', 'ham')
    if not text:
        return jsonify({'error': 'Texte requis'}), 400
    if label not in ('spam', 'ham'):
        return jsonify({'error': 'Label doit être spam ou ham'}), 400
    db.session.add(SpamModelStore(label=label, text=text))
    db.session.commit()
    invalidate_spam_cache()
    return jsonify({'message': f'Exemple {label} ajouté, modèle réentraîné'})

@app.route('/nlp/spam/examples', methods=['GET'])
def nlp_spam_examples():
    examples = SpamModelStore.query.order_by(SpamModelStore.label, SpamModelStore.id).all()
    return jsonify([{
        'id': e.id, 'label': e.label, 'text': e.text[:100],
        'created_at': e.created_at.strftime('%d/%m/%Y') if e.created_at else '',
    } for e in examples])

@app.route('/nlp/classify', methods=['POST'])
def nlp_classify():
    data = request.get_json()
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'error': 'Texte requis'}), 400
    all_prods = Product.query.filter_by(disponible=True).all()
    all_texts = [f"{p.nom} {p.description or ''}" for p in all_prods]
    tags      = NLPEngine.extract_tags(text, all_texts, n=8)
    spam_res  = NLPEngine.predict_spam(text, get_spam_model())
    similar_prods = []
    if all_prods:
        corpus      = [NLPEngine.preprocess(t) for t in [text] + all_texts]
        idf         = NLPEngine.compute_idf(corpus)
        vocab       = list(idf.keys())
        input_tfidf = NLPEngine.compute_tfidf(corpus[0], idf)
        input_vec   = NLPEngine.vectorize(input_tfidf, vocab)
        scored = []
        for i, p in enumerate(all_prods):
            p_tfidf = NLPEngine.compute_tfidf(corpus[i + 1], idf)
            p_vec   = NLPEngine.vectorize(p_tfidf, vocab)
            sim     = NLPEngine.cosine_similarity(input_vec, p_vec)
            if sim > 0.05:
                scored.append((p, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        similar_prods = [{**serialize_product(p), 'similarity': round(sim, 3)} for p, sim in scored[:5]]
    return jsonify({'tags': tags, 'spam': spam_res, 'similaires': similar_prods})

@app.route('/nlp/preprocess', methods=['POST'])
def nlp_preprocess():
    data   = request.get_json()
    text   = data.get('text', '')
    tokens = NLPEngine.preprocess(text)
    return jsonify({
        'tokens':       tokens,
        'count':        len(tokens),
        'unique':       len(set(tokens)),
        'original_len': len(text.split()),
        'reduction':    round((1 - len(tokens) / max(len(text.split()), 1)) * 100, 1),
    })

# ================================================================
# ORDERS
# ================================================================

@app.route('/orders', methods=['POST'])
def create_order():
    data               = request.get_json()
    user_id            = data.get('user_id')
    items              = data.get('items', [])
    mode               = data.get('payment_mode', 'orange')
    pickup_location_id = data.get('pickup_location_id')
    if not user_id: return jsonify({'error': 'user_id manquant'}), 400
    if not items:   return jsonify({'error': 'Panier vide'}), 400
    user = db.session.get(User, user_id)
    if not user: return jsonify({'error': 'Utilisateur introuvable'}), 404
    if pickup_location_id:
        loc = db.session.get(PickupLocation, pickup_location_id)
        if not loc or not loc.actif:
            return jsonify({'error': 'Lieu de récupération invalide'}), 400
    order = Order(user_id=user_id, payment_mode=mode,
                  status='pending', pickup_location_id=pickup_location_id)
    db.session.add(order)
    db.session.flush()
    total = 0
    for item in items:
        product  = db.session.get(Product, item.get('product_id'))
        quantity = int(item.get('quantity', 1))
        if not product or not product.disponible:
            db.session.rollback()
            return jsonify({'error': 'Produit indisponible'}), 400
        stock_dispo = product.stock - (product.stock_reserve or 0)
        if stock_dispo < quantity:
            db.session.rollback()
            return jsonify({'error': 'Stock insuffisant pour ' + product.nom}), 400
        product.stock_reserve = (product.stock_reserve or 0) + quantity
        db.session.add(OrderItem(order_id=order.id, product_id=product.id,
                                  quantity=quantity, prix_unitaire=product.prix))
        total += float(product.prix) * quantity
    order.total = total
    db.session.commit()
    return jsonify({'message': 'Commande créée', 'order_id': order.id,
                    'total': total, 'payment_mode': mode})

@app.route('/orders/<int:order_id>/submit-ref', methods=['POST'])
def submit_payment_ref(order_id):
    data  = request.get_json()
    order = db.session.get(Order, order_id)
    if not order: return jsonify({'error': 'Commande introuvable'}), 404
    if order.user_id != data.get('user_id'):
        return jsonify({'error': 'Accès refusé'}), 403
    if order.status != 'pending':
        return jsonify({'error': 'Commande non modifiable'}), 400
    ref = (data.get('payment_ref') or '').strip()
    if not ref: return jsonify({'error': 'Référence obligatoire'}), 400
    order.payment_ref = ref
    order.status      = 'awaiting_confirmation'
    db.session.commit()
    return jsonify({'message': 'Référence soumise, en attente de confirmation'})

@app.route('/orders/<int:order_id>/cancel', methods=['POST'])
def cancel_order(order_id):
    data  = request.get_json()
    order = db.session.get(Order, order_id)
    if not order: return jsonify({'error': 'Commande introuvable'}), 404
    if order.user_id != data.get('user_id'):
        return jsonify({'error': 'Accès refusé'}), 403
    if order.status != 'pending':
        return jsonify({'error': "Impossible d'annuler"}), 400
    _liberer_stock(order)
    order.status = 'cancelled'
    db.session.commit()
    return jsonify({'message': 'Commande annulée'})

@app.route('/orders/confirm', methods=['POST'])
def confirm_payment():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    order = db.session.get(Order, data.get('order_id'))
    if not order: return jsonify({'error': 'Commande introuvable'}), 404
    if order.status != 'awaiting_confirmation':
        return jsonify({'error': 'La commande doit être en awaiting_confirmation'}), 400
    for item in OrderItem.query.filter_by(order_id=order.id).all():
        product = db.session.get(Product, item.product_id)
        if product:
            product.stock         = max(0, product.stock - item.quantity)
            product.stock_reserve = max(0, (product.stock_reserve or 0) - item.quantity)
    order.status = 'ready_for_pickup' if order.pickup_location_id else 'paid'
    db.session.commit()
    return jsonify({'message': 'Paiement confirmé'})

@app.route('/orders/reject', methods=['POST'])
def reject_payment():
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    order = db.session.get(Order, data.get('order_id'))
    if not order: return jsonify({'error': 'Commande introuvable'}), 404
    if order.status not in ('awaiting_confirmation', 'pending'):
        return jsonify({'error': 'Impossible de rejeter'}), 400
    _liberer_stock(order)
    order.status = 'rejected'
    db.session.commit()
    return jsonify({'message': 'Commande rejetée, stock libéré'})

@app.route('/orders/<int:order_id>/mark-pickup', methods=['POST'])
def mark_pickup(order_id):
    data       = request.get_json()
    admin, err = require_admin(data)
    if err: return err
    order = db.session.get(Order, order_id)
    if not order: return jsonify({'error': 'Commande introuvable'}), 404
    if order.status not in ('ready_for_pickup', 'paid'):
        return jsonify({'error': 'La commande doit être prête à récupérer'}), 400
    picked_up         = bool(data.get('picked_up', True))
    order.status      = 'picked_up' if picked_up else 'not_picked_up'
    order.note_pickup = (data.get('note') or '').strip() or None
    if picked_up:
        from datetime import datetime
        order.date_pickup = datetime.utcnow()
    db.session.commit()
    msg = 'Commande marquée comme récupérée' if picked_up else 'Commande marquée comme non récupérée'
    return jsonify({'message': msg})

def _liberer_stock(order):
    for item in OrderItem.query.filter_by(order_id=order.id).all():
        product = db.session.get(Product, item.product_id)
        if product:
            product.stock_reserve = max(0, (product.stock_reserve or 0) - item.quantity)

@app.route('/orders/mine', methods=['GET'])
def get_my_orders():
    user_id = request.args.get('user_id', type=int)
    if not user_id: return jsonify({'error': 'user_id manquant'}), 400
    orders = Order.query.filter_by(user_id=user_id).order_by(Order.id.desc()).all()
    return jsonify([_serialize_order(o) for o in orders])

@app.route('/orders/awaiting', methods=['GET'])
def get_awaiting_orders():
    return jsonify([_serialize_order(o)
                    for o in Order.query.filter_by(status='awaiting_confirmation')
                                        .order_by(Order.id.desc()).all()])

@app.route('/orders/ready', methods=['GET'])
def get_ready_orders():
    return jsonify([_serialize_order(o)
                    for o in Order.query.filter_by(status='ready_for_pickup')
                                        .order_by(Order.id.desc()).all()])

@app.route('/orders/all', methods=['GET'])
def get_all_orders():
    return jsonify([_serialize_order(o)
                    for o in Order.query.order_by(Order.id.desc()).all()])



@app.route('/users/cleanup-tmp', methods=['POST'])
def cleanup_tmp_users_v2():
    """
    Supprime les users temporaires (email @mgshop.tmp) qui n'ont
    aucune commande active (pending / awaiting_confirmation).
    À appeler manuellement ou depuis un scheduler.
    """
    import datetime
    data     = request.get_json() or {}
    admin_id = data.get('admin_id')
    admin, err = require_admin({'admin_id': admin_id})
    if err: return err

    tmp_users = User.query.filter(User.email.like('%@mgshop.tmp')).all()
    deleted   = 0
    kept      = 0

    for u in tmp_users:
        # Garder si commande active
        has_active = Order.query.filter(
            Order.user_id == u.id,
            Order.status.in_(['pending', 'awaiting_confirmation', 'ready_for_pickup'])
        ).first()
        if has_active:
            kept += 1
            continue
        # Supprimer les interactions liées
        UserProductInteraction.query.filter_by(user_id=u.id).delete()
        UserCategoryInteraction.query.filter_by(user_id=u.id).delete()
        db.session.delete(u)
        deleted += 1

    db.session.commit()
    return jsonify({'message': f'{deleted} compte(s) temporaire(s) supprimé(s), {kept} conservé(s)'})
# ================================================================
# MIGRATIONS
# ================================================================

def run_migrations():
    migrations = [
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS prix_original NUMERIC(10,2)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS promotion_active BOOLEAN DEFAULT FALSE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS disponible BOOLEAN DEFAULT TRUE",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS sku VARCHAR(50)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS category_id INTEGER REFERENCES categories(id)",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_reserve INTEGER DEFAULT 0",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS tags_auto TEXT",
        "ALTER TABLE products ADD COLUMN IF NOT EXISTS spam_score FLOAT DEFAULT 0.0",
        "UPDATE products SET disponible = TRUE WHERE disponible IS NULL",
        "UPDATE products SET promotion_active = FALSE WHERE promotion_active IS NULL",
        "UPDATE products SET stock_reserve = 0 WHERE stock_reserve IS NULL",
        "ALTER TABLE badges ADD COLUMN IF NOT EXISTS product_id INTEGER REFERENCES products(id)",
        "ALTER TABLE categories ADD COLUMN IF NOT EXISTS couleur VARCHAR(20) DEFAULT '#6366f1'",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'pending'",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_mode VARCHAR(50)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_ref VARCHAR(200)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS date_creation TIMESTAMP DEFAULT NOW()",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS pickup_location_id INTEGER REFERENCES pickup_locations(id)",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS date_pickup TIMESTAMP",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS note_pickup TEXT",
        "UPDATE orders SET status = 'pending' WHERE status IS NULL",
        "UPDATE orders SET status = 'ready_for_pickup' WHERE status = 'paid' AND pickup_location_id IS NOT NULL",
        """CREATE TABLE IF NOT EXISTS user_product_interactions (
            id         SERIAL PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            nb_vues    INTEGER DEFAULT 0, nb_panier INTEGER DEFAULT 0,
            nb_achat   INTEGER DEFAULT 0, nb_ignore INTEGER DEFAULT 0,
            CONSTRAINT uq_user_product UNIQUE (user_id, product_id)
        )""",
        """CREATE TABLE IF NOT EXISTS otp_codes (
            id SERIAL PRIMARY KEY, email VARCHAR(150) NOT NULL,
            code VARCHAR(100) NOT NULL, type VARCHAR(20) NOT NULL,
            used BOOLEAN DEFAULT FALSE, created_at TIMESTAMP DEFAULT NOW()
        )""",
        "ALTER TABLE otp_codes ALTER COLUMN code TYPE VARCHAR(100)",
        "CREATE INDEX IF NOT EXISTS idx_otp_email ON otp_codes (email)",
        """CREATE TABLE IF NOT EXISTS user_category_interactions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
            nb_clics INTEGER DEFAULT 0,
            CONSTRAINT uq_user_category UNIQUE (user_id, category_id)
        )""",
        """CREATE TABLE IF NOT EXISTS spam_model_store (
            id SERIAL PRIMARY KEY, label VARCHAR(10) NOT NULL,
            text TEXT NOT NULL, created_at TIMESTAMP DEFAULT NOW()
        )""",
    ]
    with db.engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(db.text(sql))
            except Exception as e:
                print(f"[migration] ignorée : {e}")
        conn.commit()
    print("[migration] OK")


# ================================================================
# INITIALISATION — fonctionne avec Gunicorn (Render) ET python app.py (local)
# ================================================================
# ================================================================
def create_admin_if_not_exists():
    admin_email = "admin@mgshop.com"

    admin = User.query.filter_by(email=admin_email).first()

    if not admin:
        admin = User(
            nom="Admin",
            email=admin_email,
            mot_de_passe=generate_password_hash("admin123"),
            role="admin"
        )
        db.session.add(admin)
        db.session.commit()
        print("[seed] Admin créé")
    else:
        print("[seed] Admin déjà existant")


def initialize_app():
    """Appelé au démarrage (Render ou local)."""
    with app.app_context():
        db.create_all()
        run_migrations()

        # 🔥 SEED ADMIN
        create_admin_if_not_exists()

        # NLP (si tu l'utilises)
        try:
            get_spam_model()
            print("[nlp] Modèle spam initialisé")
        except Exception as e:
            print(f"[nlp] Erreur init spam : {e}")

        print("[init] MGShop prêt")


# Exécution au démarrage Gunicorn
initialize_app()


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)