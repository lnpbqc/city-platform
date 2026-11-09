"""Index object envelopes without using mutable SQLite rowids as public identity."""
from alembic import op

revision = '0013_object_rtree'
down_revision = '0012_workspace_bookmarks'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE TABLE object_spatial_keys (id INTEGER PRIMARY KEY AUTOINCREMENT, object_id VARCHAR(36) NOT NULL UNIQUE REFERENCES spatial_objects(id) ON DELETE CASCADE)')
    op.execute('CREATE VIRTUAL TABLE object_rtree USING rtree(id, west, east, south, north)')
    op.execute('INSERT INTO object_spatial_keys(object_id) SELECT id FROM spatial_objects')
    op.execute('INSERT INTO object_rtree SELECT k.id,o.west,o.east,o.south,o.north FROM spatial_objects o JOIN object_spatial_keys k ON k.object_id=o.id WHERE o.west IS NOT NULL AND o.east IS NOT NULL AND o.south IS NOT NULL AND o.north IS NOT NULL')
    op.execute('''CREATE TRIGGER object_spatial_insert AFTER INSERT ON spatial_objects BEGIN
        INSERT INTO object_spatial_keys(object_id) VALUES(NEW.id);
        INSERT INTO object_rtree SELECT id,NEW.west,NEW.east,NEW.south,NEW.north FROM object_spatial_keys
        WHERE object_id=NEW.id AND NEW.west IS NOT NULL AND NEW.east IS NOT NULL AND NEW.south IS NOT NULL AND NEW.north IS NOT NULL;
    END''')
    op.execute('''CREATE TRIGGER object_spatial_update AFTER UPDATE OF west,east,south,north ON spatial_objects BEGIN
        DELETE FROM object_rtree WHERE id=(SELECT id FROM object_spatial_keys WHERE object_id=NEW.id);
        INSERT INTO object_rtree SELECT id,NEW.west,NEW.east,NEW.south,NEW.north FROM object_spatial_keys
        WHERE object_id=NEW.id AND NEW.west IS NOT NULL AND NEW.east IS NOT NULL AND NEW.south IS NOT NULL AND NEW.north IS NOT NULL;
    END''')
    op.execute('''CREATE TRIGGER object_spatial_delete BEFORE DELETE ON spatial_objects BEGIN
        DELETE FROM object_rtree WHERE id=(SELECT id FROM object_spatial_keys WHERE object_id=OLD.id);
        DELETE FROM object_spatial_keys WHERE object_id=OLD.id;
    END''')
    op.execute('CREATE INDEX ix_objects_version_feature ON spatial_objects(asset_id, asset_version, feature_index)')


def downgrade():
    op.execute('DROP INDEX ix_objects_version_feature')
    for trigger in ('object_spatial_insert', 'object_spatial_update', 'object_spatial_delete'):
        op.execute('DROP TRIGGER ' + trigger)
    op.execute('DROP TABLE object_rtree')
    op.execute('DROP TABLE object_spatial_keys')
