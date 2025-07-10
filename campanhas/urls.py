from django.urls import path
from . import views

urlpatterns = [
    path('processar-consulta/', views.pagina_processar_consulta, name='pagina_processar_consulta'),
    path('iniciar-processamento/', views.iniciar_processamento, name='iniciar_processamento'),
    path('execucoes/', views.listar_execucoes, name='listar_execucoes'),
    path('execucao/<int:execucao_id>/', views.detalhe_execucao, name='detalhe_execucao'),
    path('execucao/<int:execucao_id>/status/', views.status_execucao_ajax, name='status_execucao_ajax'),
    path('execucao/<int:execucao_id>/exportar/', views.exportar_resultados_csv, name='exportar_resultados_csv'),
    path('execucao/<int:execucao_id>/cancelar/', views.cancelar_processamento, name='cancelar_processamento'),
    path('execucao/<int:execucao_id>/reiniciar/', views.reiniciar_processamento, name='reiniciar_processamento'),
    path('cliente/<int:cliente_id>/detalhes/', views.detalhes_cliente, name='detalhes_cliente'),
] 